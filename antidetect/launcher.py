"""Launch, track and stop Chromium processes, one per profile."""
import json
import os
import secrets
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from .paths import DATA_DIR

ENGINE_DIR = Path(
    os.environ.get("ANTIDETECT_ENGINE_DIR")
    or DATA_DIR / "squashfs-root" / "opt" / "ungoogled-chromium"
)
CHROME = ENGINE_DIR / "chrome"
CHROMEDRIVER = ENGINE_DIR / "chromedriver"
PROFILES_DIR = DATA_DIR / "profiles"

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


def build_args(profile, port, app_args=None):
    fp = profile.get("fingerprint_config") or {}
    proxy = profile.get("proxy_config") or {}
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
    if fp.get("hardware_concurrency"):
        args.append(f"--fingerprint-hardware-concurrency={int(fp['hardware_concurrency'])}")
    if fp.get("br_version"):
        args.append(f"--fingerprint-brand-version={fp['br_version']}")
    if fp.get("language"):
        args.append(f"--lang={fp['language']}")
        args.append(f"--accept-lang={fp['language']}")
    if fp.get("timezone"):
        args.append(f"--timezone={fp['timezone']}")

    proxy_type = str(proxy.get("proxy_type") or "direct").lower()
    host, proxy_port = proxy.get("proxy_ip"), proxy.get("proxy_port")
    if proxy_type != "direct" and host and proxy_port:
        if proxy.get("proxy_user") or proxy.get("proxy_password"):
            raise LaunchError("proxy dengan autentikasi belum didukung (butuh jembatan gost)")
        scheme = {"http": "http", "https": "https", "socks5": "socks5"}.get(proxy_type)
        if not scheme:
            raise LaunchError(f"proxy_type '{proxy_type}' tidak didukung")
        args.append(f"--proxy-server={scheme}://{host}:{int(proxy_port)}")

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


def _kill_pgid(pgid):
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(40):
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


def open_profile(profile, app_args=None):
    profile_id = profile["id"]
    if profile_id in _open:
        return _open[profile_id]["info"]

    port = _free_port()
    args = build_args(profile, port, app_args)
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

    info = {
        "profile_id": profile_id,
        "pid": proc.pid,
        "debugging_address": f"127.0.0.1:{port}",
        "webdriver": str(CHROMEDRIVER),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _open[profile_id] = {"proc": proc, "info": info}
    _write_state(profile_id, info)
    return info


def close_profile(profile_id):
    entry = _open.pop(profile_id, None)
    if entry is not None:
        _kill_pgid(entry["proc"].pid)
        _clear_state(profile_id)
        return True
    info = _read_state(profile_id)
    if not info:
        return False
    try:
        _kill_pgid(int(info["pid"]))
    except Exception:
        pass
    _clear_state(profile_id)
    return True


def opened_profiles():
    return [entry["info"] for entry in _open.values()]


def is_open(profile_id):
    return profile_id in _open


def forget(profile_id):
    _open.pop(profile_id, None)
    _clear_state(profile_id)
