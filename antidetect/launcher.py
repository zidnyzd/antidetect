"""Launch, track and stop Chromium processes, one per profile."""
import json
import mmap
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

from . import extensions
from .paths import DATA_DIR

ENGINE_DIR = Path(
    os.environ.get("ANTIDETECT_ENGINE_DIR")
    or DATA_DIR / "squashfs-root" / "opt" / "ungoogled-chromium"
)
CHROME = ENGINE_DIR / "chrome"
CHROMEDRIVER = ENGINE_DIR / "chromedriver"
KERNELS_DIR = DATA_DIR / "kernels"
BUILTIN_KERNEL_ID = "builtin"
PROFILES_DIR = DATA_DIR / "profiles"
GOST_FALLBACK = Path.home() / ".local" / "bin" / "gost"

GPU_FLAG_NAMES = {
    "gpu_vendor": "fingerprint-gpu-vendor",
    "gpu_renderer": "fingerprint-gpu-renderer",
    "disable_gpu_fingerprint": "disable-gpu-fingerprint",
    "disable_spoofing": "disable-spoofing",
}

_open = {}
_flag_cache = {}


def flag_supported(name, binary=None):
    """Check the engine binary for a switch name (mmap scan, cached).

    Engine 150 dropped the explicit GPU fingerprint flags, so callers gate
    them here instead of passing switches the binary silently ignores.
    """
    path = Path(binary or CHROME)
    key = (str(path), name)
    if key not in _flag_cache:
        try:
            with open(path, "rb") as handle:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as blob:
                    _flag_cache[key] = blob.find(name.encode()) >= 0
        except (OSError, ValueError):
            _flag_cache[key] = False
    return _flag_cache[key]


def kernel_support(binary=None):
    return {key: flag_supported(name, binary) for key, name in GPU_FLAG_NAMES.items()}


_kernel_versions = {}
_kernel_versions_lock = threading.Lock()


def _executable(path):
    return path.is_file() and os.access(path, os.X_OK)


def _inside_kernels(path):
    try:
        Path(path).resolve().relative_to(KERNELS_DIR.resolve())
        return True
    except (OSError, ValueError):
        return False


def _read_kernel_version(binary):
    try:
        done = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for stream in (done.stdout, done.stderr):
        for line in (stream or "").splitlines():
            line = line.strip()
            if line:
                return line
    return None


def kernel_version(binary):
    """Read chrome --version once per binary path."""
    key = str(binary)
    with _kernel_versions_lock:
        if key not in _kernel_versions:
            _kernel_versions[key] = _read_kernel_version(key)
        return _kernel_versions[key]


def available_kernels():
    """Builtin engine plus each executable KERNELS_DIR/<name>/chrome."""
    kernels = [
        {
            "id": BUILTIN_KERNEL_ID,
            "name": "Engine Bawaan",
            "version": kernel_version(CHROME),
            "path": str(CHROME),
            "active": True,
            "builtin": True,
        }
    ]
    try:
        entries = sorted(KERNELS_DIR.iterdir()) if KERNELS_DIR.is_dir() else []
    except OSError:
        entries = []
    for entry in entries:
        binary = entry / "chrome"
        if entry.name == BUILTIN_KERNEL_ID or not _executable(binary) or not _inside_kernels(binary):
            continue
        kernels.append(
            {
                "id": entry.name,
                "name": entry.name,
                "version": kernel_version(binary),
                "path": str(binary),
                "active": False,
                "builtin": False,
            }
        )
    return kernels


def kernel_for(profile):
    """Profile kernel inside KERNELS_DIR, else the builtin engine."""
    raw = str((profile.get("preference_config") or {}).get("kernel_path") or "").strip()
    if not raw:
        return CHROME
    candidate = Path(raw)
    if not _inside_kernels(candidate) or not _executable(candidate):
        return CHROME
    return candidate.resolve()


class LaunchError(Exception):
    pass


class PreferenceError(Exception):
    pass


BLOCKED_STARTUP_FLAGS = (
    "--user-data-dir",
    "--remote-debugging-port",
    "--remote-debugging-address",
    "--proxy-server",
    "--fingerprint",
    "--load-extension",
)
WINDOW_SIZE_MIN = 200
WINDOW_SIZE_MAX = 5000
WINDOW_POSITION_MIN = -10000
WINDOW_POSITION_MAX = 10000


def parse_startup_args(text):
    """Split free-form startup arguments and reject switches that change
    profile isolation or fingerprinting."""
    if text in (None, ""):
        return []
    if not isinstance(text, str):
        raise PreferenceError("argumen startup harus berupa teks")
    try:
        args = shlex.split(text)
    except ValueError:
        raise PreferenceError("tanda kutip pada argumen startup tidak seimbang")
    for arg in args:
        name = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if (
            name in BLOCKED_STARTUP_FLAGS
            or name.startswith("--fingerprint")
            or name.startswith("--remote-debugging-")
            or name.startswith("--load-extension")
        ):
            raise PreferenceError(f"argumen startup memuat flag terlarang: {name}")
        if any(character in arg for character in ("\x00", "\n", "\r")):
            raise PreferenceError("argumen startup memuat karakter terlarang")
    return args


def _preference_number(preferences, key):
    value = preferences.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise PreferenceError(f"{key} harus berupa bilangan bulat")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PreferenceError(f"{key} harus berupa bilangan bulat")
    if not number.is_integer():
        raise PreferenceError(f"{key} harus berupa bilangan bulat")
    return int(number)


def validate_preferences(preferences):
    if preferences in (None, ""):
        return
    if not isinstance(preferences, dict):
        raise PreferenceError("preference_config harus berupa objek")
    for key in ("window_width", "window_height"):
        number = _preference_number(preferences, key)
        if number is not None and not WINDOW_SIZE_MIN <= number <= WINDOW_SIZE_MAX:
            raise PreferenceError(
                f"{key} harus {WINDOW_SIZE_MIN} sampai {WINDOW_SIZE_MAX}"
            )
    for key in ("window_x", "window_y"):
        number = _preference_number(preferences, key)
        if number is not None and not WINDOW_POSITION_MIN <= number <= WINDOW_POSITION_MAX:
            raise PreferenceError(
                f"{key} harus {WINDOW_POSITION_MIN} sampai {WINDOW_POSITION_MAX}"
            )
    if "startup_args" in preferences:
        raw = preferences.get("startup_args")
        if raw not in (None, "") and not isinstance(raw, str):
            raise PreferenceError("argumen startup harus berupa teks")
        parse_startup_args(raw)


def _int_preference(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def _flag_enabled(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value is True or value == 1


def _preference_args(preferences):
    args = []
    if not isinstance(preferences, dict):
        return args
    width = _int_preference(preferences.get("window_width"))
    height = _int_preference(preferences.get("window_height"))
    if (
        width is not None
        and height is not None
        and WINDOW_SIZE_MIN <= width <= WINDOW_SIZE_MAX
        and WINDOW_SIZE_MIN <= height <= WINDOW_SIZE_MAX
    ):
        args.append(f"--window-size={width},{height}")
    x = _int_preference(preferences.get("window_x"))
    y = _int_preference(preferences.get("window_y"))
    if (
        x is not None
        and y is not None
        and WINDOW_POSITION_MIN <= x <= WINDOW_POSITION_MAX
        and WINDOW_POSITION_MIN <= y <= WINDOW_POSITION_MAX
    ):
        args.append(f"--window-position={x},{y}")
    try:
        args.extend(parse_startup_args(preferences.get("startup_args")))
    except PreferenceError:
        pass
    if _flag_enabled(preferences.get("open_devtools")):
        args.append("--auto-open-devtools-for-tabs")
    return args


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


def _gpu_args(fp, binary=None):
    """GPU fingerprint switches the installed kernel understands.

    Upstream removed --fingerprint-gpu-vendor, --fingerprint-gpu-renderer and
    --disable-gpu-fingerprint in Chrome 144; engine 150 replaced the last one
    with --disable-spoofing=gpu, which reveals the host GPU. Emit only what
    the binary actually knows so profiles never carry dead switches.
    """
    args = []
    vendor = str(fp.get("gpu_vendor") or "").strip()
    if vendor and flag_supported("fingerprint-gpu-vendor", binary):
        args.append(f"--fingerprint-gpu-vendor={vendor}")
    renderer = str(fp.get("gpu_renderer") or "").strip()
    if renderer and flag_supported("fingerprint-gpu-renderer", binary):
        args.append(f"--fingerprint-gpu-renderer={renderer}")
    if fp.get("disable_gpu_fingerprint"):
        if flag_supported("disable-gpu-fingerprint", binary):
            args.append("--disable-gpu-fingerprint")
        elif flag_supported("disable-spoofing", binary):
            args.append("--disable-spoofing=gpu")
    return args


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


def start_proxy_bridge(spec, log_dir=None, local_scheme=None, timeout=10):
    """Bridge an upstream proxy through a local gost hop.

    Chromium cannot send proxy credentials; urllib needs a plain local proxy
    for SOCKS5 and authenticated upstreams. ``local_scheme`` defaults to the
    upstream scheme (socks5 stays socks5), callers that speak HTTP can force it.
    """
    binary = _gost_binary()
    local_port = _free_port()
    if local_scheme is None:
        local_scheme = "socks5" if spec["scheme"] == "socks5" else "http"
    credentials = quote(str(spec.get("user") or ""), safe="")
    if spec.get("password"):
        credentials += ":" + quote(str(spec["password"]), safe="")
    if credentials:
        credentials += "@"
    upstream = f"{spec['scheme']}://{credentials}{spec['host']}:{spec['port']}"
    log_dir = Path(log_dir or PROFILES_DIR / "_gost")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gost.log"
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            [str(binary), "-L", f"{local_scheme}://127.0.0.1:{local_port}", "-F", upstream],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.time() + max(0.5, float(timeout))
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


def _start_gost(profile_id, spec):
    return start_proxy_bridge(spec, PROFILES_DIR / str(profile_id))


def stop_proxy_bridge(proc):
    if proc is not None and proc.poll() is None:
        _kill_pgid(proc.pid, timeout=5.0)


def build_args(profile, port, app_args=None, proxy_arg=None):
    fp = profile.get("fingerprint_config") or {}
    binary = kernel_for(profile)
    data_dir = PROFILES_DIR / str(profile["id"]) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    args = [
        str(binary),
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

    args.extend(_gpu_args(fp, binary))

    preferences = profile.get("preference_config") or {}
    args.extend(_preference_args(preferences))

    extension_ids = preferences.get("extension_ids")
    if extension_ids and not os.environ.get("ANTIDETECT_NO_EXTENSIONS"):
        paths = extensions.extension_paths(extension_ids)
        if paths:
            args.append("--load-extension=" + ",".join(str(path) for path in paths))

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


def _arrange_number(params, key, default, minimum=None):
    value = params.get(key)
    if value in (None, ""):
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if minimum is not None and number < minimum:
        return minimum
    return number


def _window_ids(pid):
    try:
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--pid", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in found.stdout.splitlines() if line.strip()]


def _move_window(window_id, x, y, width, height):
    try:
        moved = subprocess.run(
            ["wmctrl", "-i", "-r", window_id, "-e", f"0,{x},{y},{width},{height}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return moved.returncode == 0


def arrange_opened_profiles(params=None):
    """Tile open profile windows with wmctrl. A profile counts once when a
    visible window of its Chrome pid accepts the geometry change."""
    params = params or {}
    per_line = _arrange_number(params, "per_line_number_of_profiles", 3, 1)
    width = _arrange_number(params, "profile_size_width", 960, 1)
    height = _arrange_number(params, "profile_size_hight", 540, 1)
    spacing_h = _arrange_number(params, "profile_spacing_horizontal", 8, 0)
    spacing_v = _arrange_number(params, "profile_spacing_vertical", 8, 0)
    start_x = _arrange_number(params, "starting_position_x", 0)
    start_y = _arrange_number(params, "starting_position_y", 0)
    deviation_x = _arrange_number(params, "profile_deviaton_x", 0)
    deviation_y = _arrange_number(params, "profile_deviaton_y", 0)

    arranged = 0
    for index, info in enumerate(opened_profiles()):
        pid = int(info.get("pid") or 0)
        if pid <= 0:
            continue
        window_ids = _window_ids(pid)
        if not window_ids:
            continue
        row, column = divmod(index, per_line)
        x = start_x + column * (width + spacing_h + deviation_x)
        y = start_y + row * (height + spacing_v + deviation_y)
        for window_id in window_ids:
            if _move_window(window_id, x, y, width, height):
                arranged += 1
                break
    return {"arranged": arranged}


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
