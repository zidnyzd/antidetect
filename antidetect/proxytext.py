"""Text import and export for the saved proxy list."""
import base64
import time
from urllib.parse import quote, unquote

from . import store

MAX_LINES = 500
PROXY_TYPES = ("http", "https", "socks5")


class ProxyTextError(Exception):
    pass


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _proxy_type(value):
    proxy_type = str(value or "http").strip().lower()
    if proxy_type not in PROXY_TYPES:
        raise ProxyTextError(f"tipe proxy '{proxy_type}' tidak didukung, pilih http, https, atau socks5")
    return proxy_type


def _parse_line(line, default_type):
    text = line.strip()
    proxy_type = default_type
    if "://" in text:
        scheme, text = text.split("://", 1)
        proxy_type = _proxy_type(scheme)

    user, password = "", ""
    if "@" in text:
        credentials, text = text.rsplit("@", 1)
        if ":" not in credentials:
            raise ValueError("kredensial harus berbentuk user:pass@host:port")
        user, password = credentials.split(":", 1)
    parts = text.split(":")
    if len(parts) == 2:
        host, port_text = parts
    elif len(parts) == 4 and not user and not password:
        host, port_text, user, password = parts
    else:
        raise ValueError("format tidak dikenal, pakai host:port atau user:pass@host:port")

    host = host.strip()
    user = user.strip()
    if not host:
        raise ValueError("host tidak boleh kosong")
    if any(character.isspace() for character in host):
        raise ValueError("host tidak boleh memuat spasi")
    try:
        port = int(port_text.strip())
    except (TypeError, ValueError):
        raise ValueError("port harus berupa angka")
    if not 1 <= port <= 65535:
        raise ValueError("port harus 1 sampai 65535")
    return {
        "proxy_type": proxy_type,
        "proxy_ip": host,
        "proxy_port": port,
        "proxy_user": unquote(user) if user else None,
        "proxy_password": unquote(password) if password else None,
    }


def _key(proxy_type, host, port, user):
    return (
        str(proxy_type or "http").strip().lower(),
        str(host or "").strip().lower(),
        int(port) if port not in (None, "") else None,
        str(user or "").strip(),
    )


def import_text(text, default_type=None):
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise ProxyTextError("teks impor harus berupa string")
    entries = [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), 1)
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(entries) > MAX_LINES:
        raise ProxyTextError(f"maksimal {MAX_LINES} baris per impor")
    fallback = _proxy_type(default_type)

    created = 0
    skipped = 0
    errors = []
    skipped_lines = []
    with store.db() as conn:
        existing = {
            _key(row["proxy_type"], row["proxy_ip"], row["proxy_port"], row["proxy_user"])
            for row in conn.execute(
                "SELECT proxy_type, proxy_ip, proxy_port, proxy_user FROM proxies"
            )
        }
        for number, stripped in entries:
            try:
                data = _parse_line(stripped, fallback)
            except (ValueError, ProxyTextError) as error:
                errors.append({"line": number, "message": str(error)})
                continue
            key = _key(
                data["proxy_type"],
                data["proxy_ip"],
                data["proxy_port"],
                data["proxy_user"],
            )
            if key in existing:
                skipped += 1
                skipped_lines.append({"line": number, "message": "duplikat, sudah ada di daftar"})
                continue
            store.create_proxy(conn, data)
            existing.add(key)
            created += 1
    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "skipped_lines": skipped_lines,
    }


def export_proxies(include_credentials=False):
    include_credentials = _truthy(include_credentials)
    lines = []
    with store.db() as conn:
        rows = conn.execute(
            """SELECT proxy_type, proxy_ip, proxy_port, proxy_user, proxy_password
               FROM proxies ORDER BY id"""
        ).fetchall()
    for row in rows:
        host = str(row["proxy_ip"] or "").strip()
        try:
            port = int(row["proxy_port"])
        except (TypeError, ValueError):
            continue
        if not host:
            continue
        proxy_type = str(row["proxy_type"] or "http").strip().lower()
        if proxy_type not in PROXY_TYPES:
            proxy_type = "http"
        user = str(row["proxy_user"] or "").strip()
        if include_credentials and user:
            password = str(row["proxy_password"] or "")
            credentials = quote(user, safe="") + ":" + quote(password, safe="")
            lines.append(f"{proxy_type}://{credentials}@{host}:{port}")
        else:
            lines.append(f"{proxy_type}://{host}:{port}")
    content = "\n".join(lines)
    if content:
        content += "\n"
    filename = time.strftime("proxy-export-%Y%m%d-%H%M%S.txt")
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "count": len(lines),
    }
