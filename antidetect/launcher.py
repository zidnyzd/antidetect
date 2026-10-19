"""Launch, track and stop Chromium processes, one per profile."""
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .paths import DATA_DIR

ENGINE_DIR = Path(
    os.environ.get("ANTIDETECT_ENGINE_DIR")
    or DATA_DIR / "squashfs-root" / "opt" / "ungoogled-chromium"
)
CHROME = ENGINE_DIR / "chrome"
CHROMEDRIVER = ENGINE_DIR / "chromedriver"
PROFILES_DIR = DATA_DIR / "profiles"
GOST_FALLBACK = Path.home() / ".local" / "bin" / "gost"

_open = {}


class LaunchError(Exception):
    pass


def rand_seed():
    return secrets.randbelow(2**31 - 1) + 1


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _platform_arg(fp):
    value = str(fp.get("platform") or "Windows").lower()
    if value in ("windows", "win"):
        return "windows"
    if value in ("macos", "mac", "mac os"):
        return "macos"
    return None  # android/ios not supported by the engine


def _proxy_spec(profile):
    proxy = profile.get("proxy_config") or {}
    proxy_type = str(proxy.get("proxy_type") or "direct").lower()
    host, port = proxy.get("proxy_ip"), proxy.get("proxy_port")
    if proxy_type in ("direct", "", "none") or not host or not port:
        return None
    scheme = {"http": "http", "https": "https", "socks5": "socks5"}.get(proxy_type)
    if not scheme:
        raise LaunchError(f"proxy_type '{proxy_type}' tidak didukung")
    return {
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "user": str(proxy.get("proxy_user") or ""),
        "password": str(proxy.get("proxy_password") or ""),
    }


def _gost_binary():
    env = os.environ.get("ANTIDETECT_GOST")
    if env:
        return Path(env)
    found = shutil.which("gost")
    if found:
        return Path(found)
    if GOST_FALLBACK.exists():
        return GOST_FALLBACK
    raise LaunchError("gost tidak ditemukan, jalankan scripts/fetch-gost.sh dulu")


def _start_gost(profile_id, spec):
    """Bridge an authenticated upstream proxy for a Chromium that cannot do proxy auth."""
    binary = _gost_binary()
    local_port = _free_port()
    # Chromium only speaks plain http/https/socks to a local proxy; TLS to an
    # upstream HTTPS proxy is gost's job. https upstreams use a local http hop.
    local_scheme = "socks5" if spec["scheme"] == "socks5" else "http"
    credentials = quote(spec["user"], safe="")
    if spec["password"]:
        credentials += ":" + quote(spec["password"], safe="")
    if credentials:
        credentials += "@"
    upstream = f"{spec['scheme']}://{credentials}{spec['host']}:{spec['port']}"
    log_path = PROFILES_DIR / str(profile_id) / "gost.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    proc = subprocess.Popen(
        [str(binary), "-L", f"{local_scheme}://127.0.0.1:{local_port}", "-F", upstream],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            _kill_pgid(proc.pid)
            raise LaunchError(f"gost berhenti, cek {log_path}")
        try:
            socket.create_connection(("127.0.0.1", local_port), timeout=0.5).close()
            return proc, local_port
        except OSError:
            time.sleep(0.1)
    _kill_pgid(proc.pid)
    raise LaunchError(f"gost tidak mendengarkan di 127.0.0.1:{local_port}")


def build_args(profile, port, app_args=None, proxy_arg=None):
    fp = profile.get("fingerprint_config") or {}
    data_dir = PROFILES_DIR / str(profile["id"]) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    args = [
        str(CHROME),
        f"--user-data-dir={data_dir}",
        f"--fingerprint={profile['seed']}",
        "--fingerprint-brand=Chrome",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
        "--password-store=basic",
    ]
    if os.environ.get("ANTIDETECT_NO_SANDBOX") == "1":
        args.append("--no-sandbox")

    platform = _platform_arg(fp)
    if platform:
        args.append(f"--fingerprint-platform={platform}")
        if fp.get("system_version"):
            args.append(f"--fingerprint-platform-version={fp['system_version']}")
    if fp.get("hardware_concurrency"):
        args.append(f"--fingerprint-hardware-concurrency={int(fp['hardware_concurrency'])}")
    if fp.get("device_memory"):
        args.append(f"--fingerprint-memory={fp['device_memory']}")
    if fp.get("br_version"):
        args.append(f"--fingerprint-brand-version={fp['br_version']}")
    if fp.get("language"):
        args.append(f"--lang={fp['language']}")
        args.append(f"--accept-lang={fp['language']}")
    if fp.get("timezone"):
        args.append(f"--timezone={fp['timezone']}")

    if proxy_arg:
        args.append(f"--proxy-server={proxy_arg}")

    if app_args:
        args.extend(str(a) for a in app_args)
    if profile.get("site_url"):
        args.append(profile["site_url"])
    return args


def _state_path(profile_id):
    return PROFILES_DIR / str(profile_id) / "state.json"


def _write_state(profile_id, info):
    path = _state_path(profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info))


def _read_state(profile_id):
    try:
        return json.loads(_state_path(profile_id).read_text())
    except Exception:
        return None


def _clear_state(profile_id):
    try:
        _state_path(profile_id).unlink()
    except OSError:
        pass


def _process_gone(proc, pid):
    if proc is not None:
        return proc.poll() is not None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _kill_pgid(pgid, timeout=8.0):
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.2)
        try:
            os.kill(pgid, 0)
        except ProcessLookupError:
            return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _wait_for_devtools(port, deadline):
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _graceful_close(debugging_address, proc=None, pid=0, timeout=10.0):
    """Close every page target so Chromium flushes cookies before exiting."""
    if not debugging_address:
        return _process_gone(proc, pid)
    base = f"http://{debugging_address}"
    try:
        with urllib.request.urlopen(base + "/json/list", timeout=2) as response:
            targets = json.load(response)
    except Exception:
        return _process_gone(proc, pid)

    pages = [t for t in targets if t.get("type") == "page" and t.get("id")]
    if not pages:
        return False
    for target in pages:
        try:
            urllib.request.urlopen(f"{base}/json/close/{target['id']}", timeout=2).read()
        except Exception:
            pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _process_gone(proc, pid):
            return True
        time.sleep(0.1)
    return False


def _stop_gost(info):
    pid = int(info.get("gost_pid") or 0)
    if pid:
        _kill_pgid(pid, timeout=5.0)


def open_profile(profile, app_args=None):
    profile_id = profile["id"]
    if profile_id in _open:
        return _open[profile_id]["info"]

    spec = _proxy_spec(profile)
    gost_proc = None
    gost_port = None
    proxy_arg = None
    try:
        if spec:
            if spec["user"] or spec["password"]:
                gost_proc, gost_port = _start_gost(profile_id, spec)
                local_scheme = "socks5" if spec["scheme"] == "socks5" else "http"
                proxy_arg = f"{local_scheme}://127.0.0.1:{gost_port}"
            else:
                proxy_arg = f"{spec['scheme']}://{spec['host']}:{spec['port']}"

        port = _free_port()
        args = build_args(profile, port, app_args, proxy_arg=proxy_arg)
        log_path = PROFILES_DIR / str(profile_id) / "chrome.log"
        log = open(log_path, "ab")
        env = os.environ.copy()
        if not env.get("DISPLAY"):
            env["DISPLAY"] = ":0"

        proc = subprocess.Popen(
            args, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        if not _wait_for_devtools(port, time.time() + 20):
            _kill_pgid(proc.pid)
            raise LaunchError("chrome tidak menjawab di devtools port, cek chrome.log")
    except Exception:
        if gost_proc is not None:
            _kill_pgid(gost_proc.pid, timeout=5.0)
        _clear_state(profile_id)
        raise

    info = {
        "profile_id": profile_id,
        "pid": proc.pid,
        "debugging_address": f"127.0.0.1:{port}",
        "webdriver": str(CHROMEDRIVER),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "proxy": proxy_arg,
        "gost_pid": gost_proc.pid if gost_proc else None,
    }
    _open[profile_id] = {"proc": proc, "info": info}
    _write_state(profile_id, info)
    return info


def close_profile(profile_id):
    entry = _open.pop(profile_id, None)
    info = entry["info"] if entry else _read_state(profile_id)
    if not info:
        return False
    proc = entry["proc"] if entry else None
    pid = int(info.get("pid") or 0)
    if not _graceful_close(info.get("debugging_address"), proc=proc, pid=pid) and pid:
        _kill_pgid(pid)
    _stop_gost(info)
    _clear_state(profile_id)
    return True


def opened_profiles():
    return [entry["info"] for entry in _open.values()]


def is_open(profile_id):
    return profile_id in _open


def forget(profile_id):
    entry = _open.pop(profile_id, None)
    info = entry["info"] if entry else _read_state(profile_id)
    if info:
        pid = int(info.get("pid") or 0)
        if not pid or _process_gone(None, pid):
            _stop_gost(info)
    _clear_state(profile_id)
