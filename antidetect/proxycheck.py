"""Check a proxy by fetching the public IP through it."""
import json
import socket
import time
import urllib.error
import urllib.request

from . import launcher, store
from .paths import DATA_DIR

CHECK_URL = "https://api.ipify.org?format=json"
TIMEOUT = 10
SUPPORTED_TYPES = ("direct", "http", "https", "socks5")
LOG_DIR = DATA_DIR / "proxycheck"


def _config(params):
    row = None
    proxy_id = params.get("proxy_id")
    if proxy_id not in (None, ""):
        try:
            proxy_id = int(proxy_id)
        except (TypeError, ValueError):
            return None, "proxy_id tidak valid"
        with store.db() as conn:
            row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        if row is None:
            return None, "Proxy tidak ditemukan"
    config = dict(row) if row is not None else {}
    for key in ("proxy_type", "proxy_ip", "proxy_port", "proxy_user", "proxy_password"):
        if params.get(key) is not None:
            config[key] = params.get(key)
    return config, None


def _proxy_spec(config):
    proxy_type = str(config.get("proxy_type") or "direct").strip().lower()
    if proxy_type in ("", "none"):
        proxy_type = "direct"
    if proxy_type not in SUPPORTED_TYPES:
        raise ValueError(f"proxy_type '{proxy_type}' tidak didukung")
    if proxy_type == "direct":
        return None
    host = str(config.get("proxy_ip") or "").strip()
    if not host:
        raise ValueError("Host proxy wajib diisi")
    try:
        port = int(config.get("proxy_port"))
    except (TypeError, ValueError):
        raise ValueError("Port proxy tidak valid")
    if port < 1 or port > 65535:
        raise ValueError("Port proxy harus 1 sampai 65535")
    return {
        "scheme": proxy_type,
        "host": host,
        "port": port,
        "user": str(config.get("proxy_user") or ""),
        "password": str(config.get("proxy_password") or ""),
    }


def _fail(message):
    return {"ok": False, "error": str(message) or "cek proxy gagal"}


def _proxy_id(params):
    value = params.get("proxy_id")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _save_check(proxy_id, result):
    """Simpan hasil cek ke riwayat. Gagal menyimpan tidak boleh merusak cek."""
    if proxy_id is None:
        return
    try:
        with store.db() as conn:
            if conn.execute(
                "SELECT 1 FROM proxies WHERE id = ?", (proxy_id,)
            ).fetchone() is None:
                return
            store.add_proxy_check(
                conn,
                proxy_id,
                bool(result.get("ok")),
                result.get("ip"),
                result.get("latency_ms"),
                result.get("error"),
            )
    except Exception:
        pass


def check_proxy(params, record_history=True):
    """Cek proxy. record_history=False dipakai untuk validasi pra simpan."""
    params = params or {}
    result = _run_check(params)
    if record_history:
        _save_check(_proxy_id(params), result)
    return result


def _run_check(params):
    started = time.monotonic()
    deadline = started + TIMEOUT
    config, error = _config(params)
    if error:
        return _fail(error)
    try:
        spec = _proxy_spec(config)
    except ValueError as exc:
        return _fail(exc)

    bridge = None
    try:
        if spec is None:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        elif spec["scheme"] in ("http", "https") and not (spec["user"] or spec["password"]):
            proxy_url = f"{spec['scheme']}://{spec['host']}:{spec['port']}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )
        else:
            bridge_budget = max(0.5, min(5.0, deadline - time.monotonic()))
            bridge, local_port = launcher.start_proxy_bridge(
                spec, log_dir=LOG_DIR, local_scheme="http", timeout=bridge_budget
            )
            proxy_url = f"http://127.0.0.1:{local_port}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )

        remaining = max(1.0, deadline - time.monotonic())
        request = urllib.request.Request(
            CHECK_URL, headers={"User-Agent": "antidetect-proxycheck/1.0"}
        )
        with opener.open(request, timeout=remaining) as response:
            payload = json.loads(response.read(4096).decode("utf-8", "replace"))
        ip = payload.get("ip") if isinstance(payload, dict) else None
        if not ip:
            return _fail("Respons cek IP tidak berisi alamat")
        latency = int(round((time.monotonic() - started) * 1000))
        return {"ok": True, "ip": ip, "latency_ms": latency}
    except urllib.error.HTTPError as exc:
        return _fail(f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return _fail(exc.reason)
    except (TimeoutError, socket.timeout):
        return _fail("Cek proxy timeout")
    except Exception as exc:  # keep the API contract: never raise from a check
        return _fail(exc)
    finally:
        if bridge is not None:
            launcher.stop_proxy_bridge(bridge)
