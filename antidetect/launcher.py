"""Launch, track and stop Chromium processes, one per profile."""
import json
import mmap
import os
import re
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
# Launcher wajib melewati wrapper ini, yang menegakkan batas instance hidup,
# batas laju peluncuran, dan lokasi user-data-dir.
ENGINE_WRAPPER = Path.home() / ".local" / "bin" / "antidetect-engine-wrapper.py"

GPU_FLAG_NAMES = {
    "gpu_vendor": "fingerprint-gpu-vendor",
    "gpu_renderer": "fingerprint-gpu-renderer",
    "disable_gpu_fingerprint": "disable-gpu-fingerprint",
    "disable_spoofing": "disable-spoofing",
}
DISABLE_SPOOFING_VALUES = ("font", "audio", "canvas", "clientrects", "gpu")
# Hanya dua dari lima nilai yang terukur mengubah apa pun di engine 150.
# font, audio, dan clientrects diterima engine lalu diabaikan diam-diam.
DISABLE_SPOOFING_EFFECTIVE = ("canvas", "gpu")
WEBRTC_MODES = (0, 1, 2, 3, 4)

# Engine 150 mengalikan lebar teks canvas dengan faktor noise yang hanya
# bergantung pada seed. Faktor negatif menghasilkan lebar font negatif,
# sesuatu yang mustahil terjadi di browser asli.
# Tabel di bawah diisi dari pengukuran nyata pada engine 150: bit ke-i
# menandai seed SEED_SAFE_BASE + i yang menghasilkan faktor nonnegatif.
# Batasnya: tabel hanya berlaku untuk seed di dalam rentang tersebut dan
# untuk engine 150, di luar itu seed dianggap belum terverifikasi.
SEED_SAFE_BASE = 1_000_000_000
SEED_SAFE_COUNT = 4096
SEED_SAFE_BITMAP = (
    "d1d406a001e5c239389ca55fd40c542ed1a57c2e417395764c9b95376d2b75fa9a92bf34b8c83fe9332624b28d011200"
    "1116d4d98b699643047fb8980237fd20420f06c311f0f87d559de725bfa50bc9d62b5d020d1f4c1b79aeb3348bd12259"
    "5712a5f63bb7f7a5073cc7d4b7a617b3a5d47a1f829b30b60f2ed5e4fb99b046cbef585e958e7d2e0a59be1b94fe3046"
    "17e99b7679e542c6c7bf537291e06a32eb9ea6af2deedaad782b4170ea746781aa58b62d55abff18ac76d464cd5ec47c"
    "0edb7d5f0aa9e85cccb532e6699351a0f5af4273bffa414664f850c9b2cd343cbc591aad0a8b4a3f99ae5b892967d968"
    "d45abe7dbceb47f4b315170f8dd2c61ce9ca3f261cbfd0615915370785fbaa79a954a0d8842fad684b102e1ebd96c4ce"
    "a5e6c3d40f73745e481a37bff7beaf9548cea78d8367e6c3e84719907c0db69cb61cc4854885242491556f5008e0318e"
    "825405df56c3ef4c8cc2ce1989f3d8877f47af75cd3c172892968483072fed69dd1ffae9bc7b213b107bab0245c79bd9"
    "491548b5fdaf92af67850fe678a56d316fce30f7e5b139809ce53a91ea8fbb82a1ca4d0e053e7260e7dae94a61386304"
    "afff889ffab565b6d681f599cf268487cf927e17da63cfaada38d10b905362743748b493893ff2625bbca04cabd21d5f"
    "d8a9907487f67d95b48b4bf6d84bce785cb59ca70207e78294bed1949fc05782"
)

SEED_SAFE_BYTES = bytes.fromhex(SEED_SAFE_BITMAP)
SEED_SAFE_COUNT = min(SEED_SAFE_COUNT, len(SEED_SAFE_BYTES) * 8)
SEED_SAFE_INDEXES = tuple(
    index
    for index in range(SEED_SAFE_COUNT)
    if SEED_SAFE_BYTES[index // 8] & (1 << (index % 8))
)

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
    support = {key: flag_supported(name, binary) for key, name in GPU_FLAG_NAMES.items()}
    support["disable_spoofing_effective"] = list(DISABLE_SPOOFING_EFFECTIVE)
    return support


def max_kernel_version():
    """Highest installed kernel number, as ixBrowser reports it."""
    highest = 0
    for kernel in available_kernels():
        for part in str(kernel.get("version") or "").replace(".", " ").split():
            if part.isdigit():
                highest = max(highest, int(part))
                break
        for part in str(kernel.get("name") or "").split():
            if part.isdigit():
                highest = max(highest, int(part))
                break
    return highest


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
    if "block_permission_requests" in preferences:
        value = _int_preference(preferences.get("block_permission_requests"))
        if value is not None and value not in (0, 1):
            raise PreferenceError("block_permission_requests harus 0 atau 1")
    if "multi_instance" in preferences:
        value = _int_preference(preferences.get("multi_instance"))
        if value is not None and value not in (0, 1):
            raise PreferenceError("multi_instance harus 0 atau 1")
    _apply_preference_conflicts(preferences)


def _apply_preference_conflicts(preferences):
    """Mirror the ixBrowser rules where one switch forces another off."""
    if not isinstance(preferences, dict):
        return preferences
    multi = _int_preference(preferences.get("multi_instance"))
    cookies = _int_preference(preferences.get("cookies_backup"))
    if multi == 1:
        preferences["cookies_backup"] = 0
        preferences["is_tabs_cache"] = 0
    elif cookies == 1:
        preferences["multi_instance"] = 0
    elif cookies == 0 and "cookies_backup" in preferences:
        for key in ("indexed_db_backup", "local_storage_backup", "extension_data_backup"):
            preferences[key] = 0
    return preferences


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


def parse_disable_spoofing(value):
    """Normalize fingerprint_config.disable_spoofing to known switch names."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            if isinstance(item, str) and "," in item:
                items.extend(item.split(","))
            else:
                items.append(item)
    else:
        raise PreferenceError("disable_spoofing harus berupa teks atau daftar")

    chosen = []
    for item in items:
        if not isinstance(item, str):
            raise PreferenceError("disable_spoofing hanya menerima nama komponen teks")
        name = item.strip().lower()
        if not name:
            continue
        if name not in DISABLE_SPOOFING_VALUES:
            raise PreferenceError(
                "disable_spoofing tidak dikenal: "
                f"{name}, pilih salah satu dari {', '.join(DISABLE_SPOOFING_VALUES)}"
            )
        if name not in chosen:
            chosen.append(name)
    return [name for name in DISABLE_SPOOFING_VALUES if name in chosen]


def effective_disable_spoofing(values):
    """Only the components the engine actually honours.

    font, audio and clientrects are accepted by the binary and then ignored.
    """
    if isinstance(values, str):
        values = values.split(",")
    chosen = {str(item).strip().lower() for item in (values or []) if str(item).strip()}
    return [name for name in DISABLE_SPOOFING_EFFECTIVE if name in chosen]


def validate_fingerprint(fingerprint):
    """Check the fingerprint fields the engine can police."""
    if fingerprint in (None, ""):
        return
    if not isinstance(fingerprint, dict):
        raise PreferenceError("fingerprint_config harus berupa objek")
    parse_disable_spoofing(fingerprint.get("disable_spoofing"))
    webrtc = fingerprint.get("webrtc")
    if webrtc not in (None, ""):
        try:
            value = int(webrtc)
        except (TypeError, ValueError):
            raise PreferenceError("webrtc harus berupa angka 0 sampai 4")
        if value not in WEBRTC_MODES:
            raise PreferenceError(
                "webrtc harus salah satu dari " + ", ".join(str(m) for m in WEBRTC_MODES)
            )


def normalize_switch(value):
    """Accept both the SDK (0/1) and the ixBrowser bundle (1/2) conventions.

    Returns 1 for active and 0 for inactive.
    """
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (None, ""):
        return 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return 1
    return 0


def normalize_use_system_proxy(value):
    """Accept the bundle string form and the SDK integer form."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("disable", "disabled", "off", "no"):
            return 3
        if text in ("enable", "enabled", "on", "yes"):
            return 2
        if text in ("follow", "global", "default"):
            return 1
        return value
    try:
        number = int(value)
    except (TypeError, ValueError):
        return value
    return number if number in (1, 2, 3) else value


def normalize_proxy_extraction_method(value):
    """Accept invalid, every_type and the bundle-only handle."""
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    return text if text in ("invalid", "every_type", "handle") else value


def validate_proxy(proxy):
    """Normalisasi field proxy yang punya dua konvensi nilai."""
    if not isinstance(proxy, dict):
        return proxy
    if "use_system_proxy" in proxy:
        proxy["use_system_proxy"] = normalize_use_system_proxy(proxy["use_system_proxy"])
    if "proxy_extraction_method" in proxy:
        proxy["proxy_extraction_method"] = normalize_proxy_extraction_method(
            proxy["proxy_extraction_method"]
        )
    return proxy


def _preference_args(preferences, binary=None):
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
    if _flag_enabled(preferences.get("block_permission_requests")) and flag_supported(
        "deny-permission-prompts", binary
    ):
        args.append("--deny-permission-prompts")
    return args


def seed_is_safe(seed):
    """True kalau seed terverifikasi menghasilkan faktor noise nonnegatif.

    Sumber kebenaran adalah tabel hasil pengukuran pada engine 150. Seed
    di luar rentang tabel belum terverifikasi dan dianggap tidak aman.
    """
    number = _int_preference(seed)
    if number is None:
        return False
    index = number - SEED_SAFE_BASE
    if index < 0 or index >= SEED_SAFE_COUNT:
        return False
    return bool(SEED_SAFE_BYTES[index // 8] & (1 << (index % 8)))


def rand_seed():
    """Seed acak dari subset yang terverifikasi tidak menghasilkan lebar negatif."""
    if not SEED_SAFE_INDEXES:
        raise LaunchError("tabel seed aman kosong, engine tidak bisa dipakai")
    return SEED_SAFE_BASE + SEED_SAFE_INDEXES[secrets.randbelow(len(SEED_SAFE_INDEXES))]


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


def _webrtc_args(fp):
    """Map the ixBrowser WebRTC mode onto the switches the engine knows.

    Mode 0 off, 1 replace the public IP with the proxy IP and mask the local
    IP, 2 keep the real IP, 3 forward through Google, 4 disable UDP.

    The engine has no single switch for this, so the closest real switches
    are used. Mode 3 and 4 need a proxy extension that does not exist here,
    so mode 3 falls back to the closest available behaviour and mode 4 adds
    the non-proxied UDP block.
    """
    mode = fp.get("webrtc")
    if mode in (None, ""):
        return []
    try:
        mode = int(mode)
    except (TypeError, ValueError):
        return []
    if mode not in WEBRTC_MODES:
        return []

    args = []
    if mode == 0:
        # WebRTC off: block the peer connection and hide local addresses.
        args.append("--disable-webrtc-encryption")
        args.append("--enable-webrtc-hide-local-ips-with-mdns")
        args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")
        return args
    if mode == 1:
        # Replace the public IP with the proxy IP and mask the local IP.
        args.append("--webrtc-ip-handling-policy=default_public_interface_only")
        args.append("--enable-webrtc-hide-local-ips-with-mdns")
        return args
    if mode == 2:
        # Keep the real IP; nothing to add.
        return args
    if mode == 3:
        # Google forwarding needs a proxy extension, so keep the real
        # interfaces and let the proxy handle the public address.
        args.append("--webrtc-ip-handling-policy=default_public_and_private_interfaces")
        return args
    if mode == 4:
        # Disable UDP so non-proxied UDP traffic cannot leak.
        args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")
        return args
    return args


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

    disabled = set(parse_disable_spoofing(fp.get("disable_spoofing")))
    if _flag_enabled(fp.get("disable_gpu_fingerprint")):
        disabled.add("gpu")
    ordered = [name for name in DISABLE_SPOOFING_VALUES if name in disabled]
    if not ordered:
        return args

    if flag_supported("disable-spoofing", binary):
        args.append("--disable-spoofing=" + ",".join(ordered))
    elif ordered == ["gpu"] and flag_supported("disable-gpu-fingerprint", binary):
        args.append("--disable-gpu-fingerprint")
    return args


def _proxy_spec(profile):
    proxy = validate_proxy(profile.get("proxy_config") or {})
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


def build_args(profile, port, app_args=None, proxy_arg=None, data_dir=None):
    fp = profile.get("fingerprint_config") or {}
    validate_fingerprint(fp)
    binary = kernel_for(profile)
    if data_dir is None:
        data_dir = PROFILES_DIR / str(profile["id"]) / "data"
    data_dir = Path(data_dir)
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

    args.extend(_webrtc_args(fp))
    args.extend(_gpu_args(fp, binary))

    preferences = profile.get("preference_config") or {}
    args.extend(_preference_args(preferences, binary))

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
    return _wrap_engine_args(args, binary)


def _wrap_engine_args(args, binary):
    """Route the engine launch through the guard wrapper.

    The wrapper refuses a launch when too many engine windows are alive, when
    the launch rate is too high, or when the data directory sits outside the
    allowed locations. Without it a probe script can flood the machine.
    """
    if os.environ.get("ANTIDETECT_ENGINE_GUARD") == "0":
        return args
    wrapper = Path(ENGINE_WRAPPER)
    if not wrapper.is_file():
        return args
    engine_args = [arg for arg in args if arg != str(binary)]
    return [str(wrapper), "--engine", str(binary), "--"] + engine_args


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


def _multi_instance_enabled(profile):
    preferences = profile.get("preference_config") or {}
    return _int_preference(preferences.get("multi_instance")) == 1


def _state_instances(state):
    """Daftar instance yang tercatat di state.json profil."""
    if not isinstance(state, dict):
        return []
    instances = state.get("instances")
    if isinstance(instances, list):
        return [item for item in instances if isinstance(item, dict)]
    if state.get("pid"):
        return [state]
    return []

def _instance_data_dir(profile_id, index):
    """Direktori data instance ke-index.

    Instance pertama memakai 'data', instance berikutnya 'data-2', 'data-3'.
    """
    name = "data" if index <= 1 else f"data-{index}"
    return PROFILES_DIR / str(profile_id) / name

def _instance_dir_busy(path):
    """True kalau direktori data sedang dipakai proses Chrome lain."""
    lock = Path(path) / "SingletonLock"
    target = ""
    try:
        target = os.readlink(lock)
    except OSError:
        try:
            target = lock.read_text().strip()
        except OSError:
            return False
    tail = target.rsplit("-", 1)[-1].strip()
    if not tail.isdigit():
        return True
    return not _process_gone(None, int(tail))

def _live_instance_indexes(profile_id):
    """Nomor instance yang sedang dipakai proses hidup."""
    indexes = set()
    entry = _open.get(profile_id)
    records = []
    if entry:
        records = [item["info"] for item in entry.get("instances") or []]
    else:
        records = _state_instances(_read_state(profile_id))
    for info in records:
        index = int(info.get("instance") or 1)
        pid = int(info.get("pid") or 0)
        if pid and not _process_gone(None, pid):
            indexes.add(index)
    return indexes

def _free_instance_index(profile_id):
    """Nomor instance berikutnya yang direktori datanya belum dipakai."""
    busy = _live_instance_indexes(profile_id)
    index = 1
    while True:
        if index not in busy and not _instance_dir_busy(_instance_data_dir(profile_id, index)):
            return index
        index += 1

def _state_payload(profile_id):
    """Isi state.json: instance utama di atas, daftar instance di bawah."""
    entry = _open.get(profile_id)
    if entry is None:
        return {}
    instances = [item["info"] for item in entry.get("instances") or []]
    if not instances:
        return dict(entry.get("info") or {})
    payload = dict(instances[0])
    payload["instances"] = instances
    return payload


def open_profile(profile, app_args=None):
    profile_id = profile["id"]
    if profile_id in _open and not _multi_instance_enabled(profile):
        return _open[profile_id]["info"]

    spec = _proxy_spec(profile)
    gost_proc = None
    gost_port = None
    proxy_arg = None
    instance_index = _free_instance_index(profile_id) if _multi_instance_enabled(profile) else 1
    data_dir = _instance_data_dir(profile_id, instance_index) if _multi_instance_enabled(profile) else None
    try:
        if spec:
            if spec["user"] or spec["password"]:
                gost_proc, gost_port = _start_gost(profile_id, spec)
                local_scheme = "socks5" if spec["scheme"] == "socks5" else "http"
                proxy_arg = f"{local_scheme}://127.0.0.1:{gost_port}"
            else:
                proxy_arg = f"{spec['scheme']}://{spec['host']}:{spec['port']}"

        port = _free_port()
        try:
            args = build_args(profile, port, app_args, proxy_arg=proxy_arg, data_dir=data_dir)
        except PreferenceError as error:
            raise LaunchError(str(error)) from error
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
        "data_dir": str(data_dir) if data_dir else str(PROFILES_DIR / str(profile_id) / "data"),
        "instance": instance_index,
    }
    if _multi_instance_enabled(profile):
        # Several instances may run, so keep them all in a list per profile.
        _open.setdefault(profile_id, {"proc": None, "info": info, "instances": []})
        _open[profile_id]["instances"].append({"proc": proc, "info": info})
        _open[profile_id]["info"] = info
    else:
        _open[profile_id] = {"proc": proc, "info": info}
    _write_state(profile_id, _state_payload(profile_id))
    return info


def close_profile(profile_id):
    entry = _open.pop(profile_id, None)
    info = entry["info"] if entry else _read_state(profile_id)
    if not info:
        return False
    instances = entry.get("instances") if entry else None
    if instances:
        closed = 0
        for item in instances:
            item_info = item["info"]
            item_pid = int(item_info.get("pid") or 0)
            if not _graceful_close(item_info.get("debugging_address"), proc=item["proc"], pid=item_pid) and item_pid:
                _kill_pgid(item_pid)
            _stop_gost(item_info)
            closed += 1
        _clear_state(profile_id)
        return closed > 0
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


def _arrange_param(params, keys, default, minimum=None):
    """Ambil angka tata letak dari nama pertama yang ada di payload.

    Bundle dan kode lama memakai ejaan berbeda untuk beberapa parameter,
    jadi semua ejaan yang dikenal diterima.
    """
    for key in keys:
        if key in params:
            return _arrange_number(params, key, default, minimum)
    return default


def _screen_areas():
    """Daftar area layar dari xrandr sebagai (x, y, lebar, tinggi)."""
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return []
    areas = []
    for line in (result.stdout or "").splitlines():
        if " connected" not in line:
            continue
        found = re.search(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", line)
        if found:
            areas.append(
                (
                    int(found.group(3)),
                    int(found.group(4)),
                    int(found.group(1)),
                    int(found.group(2)),
                )
            )
    return areas


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
    per_line = _arrange_param(params, ("per_line_number_of_profiles",), 3, 1)
    width = _arrange_param(params, ("profile_size_width",), 960, 1)
    height = _arrange_param(params, ("profile_size_hight",), 540, 1)
    spacing_h = _arrange_param(
        params, ("profile_spacing_horizontal", "profile_spaceing_horizontal"), 8, 0
    )
    spacing_v = _arrange_param(
        params, ("profile_spacing_vertical", "profile_spaceing_vertical"), 8, 0
    )
    start_x = _arrange_param(params, ("starting_position_x",), 0)
    start_y = _arrange_param(params, ("starting_position_y",), 0)
    # The bundle spells it profile_deviation_x; the earlier API used a typo.
    deviation_x = _arrange_param(params, ("profile_deviation_x", "profile_deviaton_x"), 0)
    deviation_y = _arrange_param(params, ("profile_deviation_y", "profile_deviaton_y"), 0)
    layout = _arrange_param(params, ("layout",), 1)
    adaptive = _arrange_param(params, ("adaptive",), 0)
    screen = _arrange_param(params, ("screen",), 0, 0)

    origin_x = 0
    origin_y = 0
    if adaptive == 1:
        areas = _screen_areas()
        if areas:
            index = min(screen, len(areas) - 1)
            origin_x, origin_y, area_w, area_h = areas[index]
            width = min(width, area_w)
            height = min(height, area_h)

    arranged = 0
    for index, info in enumerate(opened_profiles()):
        pid = int(info.get("pid") or 0)
        if pid <= 0:
            continue
        window_ids = _window_ids(pid)
        if not window_ids:
            continue
        row, column = divmod(index, per_line)
        if layout == 0:
            # Stack: every window shares the same origin, offset by deviation.
            x = start_x + index * deviation_x
            y = start_y + index * deviation_y
        else:
            x = origin_x + start_x + column * (width + spacing_h + deviation_x)
            y = origin_y + start_y + row * (height + spacing_v + deviation_y)
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
