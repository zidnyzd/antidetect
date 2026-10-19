"""End-to-end proxy authentication test with a local CONNECT proxy.

The proxy requires HTTP Basic auth and logs every request. The browser part
talks to the local API and Selenium; the proxy itself is stdlib only.

    ./venv/bin/python scripts/test-auth-proxy.py            # full e2e
    ./venv/bin/python scripts/test-auth-proxy.py --serve    # proxy only
"""
import argparse
import base64
import json
import os
import select
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
API = "http://127.0.0.1:53200/api/v2/"
SITE = "https://example.com"

LOG = []
LOG_LOCK = threading.Lock()


def log(line):
    with LOG_LOCK:
        LOG.append(line)
    print(line, flush=True)


class AuthProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "authproxy/1.0"

    def log_message(self, fmt, *args):
        pass

    def _credentials(self):
        raw = self.headers.get("Proxy-Authorization") or ""
        scheme, _, token = raw.partition(" ")
        if scheme.lower() != "basic" or not token:
            return None
        try:
            decoded = base64.b64decode(token).decode("utf-8")
        except Exception:
            return None
        user, sep, password = decoded.partition(":")
        return (user, password) if sep else None

    def _authorized(self):
        return self._credentials() == (self.server.user, self.server.password)

    def _reply(self, code, reason=None):
        self.send_response(code, reason)
        if code == 407:
            self.send_header("Proxy-Authenticate", 'Basic realm="antidetect-test"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_CONNECT(self):
        auth = self.headers.get("Proxy-Authorization")
        log(f"CONNECT {self.path} auth={'yes' if auth else 'no'} header={auth!r}")
        if not self._authorized():
            log(f"DENY 407 {self.path}")
            self._reply(407, "Proxy Authentication Required")
            return
        host, _, port = self.path.rpartition(":")
        host = host.strip("[]")
        try:
            upstream = socket.create_connection((host, int(port)), timeout=10)
        except OSError as error:
            log(f"UPSTREAM-FAIL {self.path}: {error}")
            self._reply(502, "Bad Gateway")
            return
        log(f"ALLOW {self.path}")
        self.send_response(200, "Connection Established")
        self.end_headers()
        try:
            self._tunnel(self.connection, upstream)
        finally:
            upstream.close()

    def _tunnel(self, client, upstream):
        sockets = [client, upstream]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], 30)
                if not readable:
                    return
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    (upstream if sock is client else client).sendall(data)
        finally:
            self.close_connection = True


class AuthProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_proxy(user, password, port=0):
    server = AuthProxyServer(("127.0.0.1", port), AuthProxyHandler)
    server.user = user
    server.password = password
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def api(action, payload):
    request = urllib.request.Request(
        API + action,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    if body["error"]["code"] != 0:
        raise RuntimeError(f"{action}: {body['error']}")
    return body["data"]


def make_profile(name, proxy_port, user, password):
    data = api(
        "profile-create",
        {
            "name": name,
            "site_id": 22,
            "fingerprint_config": {"platform": "Windows"},
            "proxy_config": {
                "proxy_mode": 2,
                "proxy_type": "http",
                "proxy_ip": "127.0.0.1",
                "proxy_port": proxy_port,
                "proxy_user": user,
                "proxy_password": password,
            },
        },
    )
    return data["profile_id"]


def attach(info):
    from selenium.webdriver import Chrome
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_experimental_option("debuggerAddress", info["debugging_address"])
    return Chrome(service=Service(info["webdriver"]), options=options)


def pid_gone(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
    except OSError:
        return True
    return state == "Z"


def run_browser(pid, label):
    info = api("profile-open", {"profile_id": pid, "args": ["--headless"]})
    log(f"{label}: open info gost_pid={info.get('gost_pid')} proxy={info.get('proxy')}")
    driver = attach(info)
    driver.set_page_load_timeout(25)
    error = None
    try:
        driver.get(SITE)
    except Exception as exc:
        error = exc
        log(f"{label}: navigation error: {exc.__class__.__name__}: {exc}")
    title = driver.title
    source = driver.page_source or ""
    log(f"{label}: title={title!r} contains_example={'Example Domain' in source}")
    driver.service.stop()
    closed = api("profile-close", {"profile_id": pid})
    log(f"{label}: close={closed}")
    if info.get("gost_pid"):
        for _ in range(50):
            if pid_gone(info["gost_pid"]):
                break
            time.sleep(0.1)
        log(f"{label}: gost gone={pid_gone(info['gost_pid'])}")
    return title, source, error, info


def e2e():
    try:
        urllib.request.urlopen("http://127.0.0.1:53200/health", timeout=5).read()
    except Exception:
        sys.exit("API server is not running on 127.0.0.1:53200")

    server = start_proxy("demo", "s3cr3t")
    port = server.server_address[1]
    log(f"auth proxy listening on 127.0.0.1:{port} user=demo password=s3cr3t")

    good = make_profile("proxyauth-ok", port, "demo", "s3cr3t")
    log(f"created good profile {good}")
    title, source, error, _ = run_browser(good, "good")

    log("--- assertions (good credentials) ---")
    connect_lines = [line for line in LOG if line.startswith("CONNECT ")]
    allow_lines = [line for line in LOG if line.startswith("ALLOW ")]
    assert any("example.com:443" in line for line in connect_lines), "no CONNECT to example.com:443"
    assert any("auth=yes" in line for line in connect_lines), "no Proxy-Authorization on CONNECT"
    assert allow_lines, "proxy did not authorize the tunnel"
    assert error is None, f"navigation failed with correct credentials: {error}"
    assert "Example Domain" in source, "page did not load through the authenticated proxy"
    print("PASS: authenticated CONNECT seen and page loaded")

    bad = make_profile("proxyauth-bad", port, "demo", "wrong-password")
    log(f"created bad profile {bad}")
    bad_title, bad_source, bad_error, _ = run_browser(bad, "bad")

    log("--- assertions (wrong credentials, fail closed) ---")
    deny_lines = [line for line in LOG if line.startswith("DENY 407 ")]
    assert deny_lines, "proxy never rejected the wrong credentials"
    assert "Example Domain" not in bad_source, "page loaded despite wrong proxy credentials"
    assert bad_title != "Example Domain", "page title leaked through with wrong credentials"
    print(f"PASS: wrong credentials rejected (title={bad_title!r}, nav_error={bad_error})")

    for pid in (good, bad):
        api("profile-delete", {"profile_id": pid})
        log(f"deleted test profile {pid}")
    server.shutdown()
    print("PASS: proxy auth e2e")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="run the proxy only")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--user", default="demo")
    parser.add_argument("--password", default="s3cr3t")
    args = parser.parse_args()

    if args.serve:
        server = start_proxy(args.user, args.password, args.port)
        log(f"auth proxy listening on 127.0.0.1:{server.server_address[1]}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    e2e()


if __name__ == "__main__":
    main()
