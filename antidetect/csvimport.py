"""Import profiles from a flat CSV file."""
import csv
import io
from urllib.parse import urlsplit

from . import store

MAX_BYTES = 1024 * 1024
MAX_ROWS = 500
COLUMNS = (
    "name",
    "group",
    "note",
    "platform",
    "system_version",
    "proxy_type",
    "proxy_ip",
    "proxy_port",
    "proxy_user",
    "proxy_password",
    "site_url",
)
PLATFORM_VERSIONS = {
    "windows": ("Windows", ("11", "10", "8.1", "7")),
    "macos": ("Macos", ("14", "13", "12")),
}
PROXY_TYPES = ("http", "https", "socks5")


class CsvImportError(Exception):
    pass


def _cell(row, index):
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def _proxy_values(row, columns):
    return (
        _cell(row, columns.get("proxy_type")).lower(),
        _cell(row, columns.get("proxy_ip")),
        _cell(row, columns.get("proxy_port")),
        _cell(row, columns.get("proxy_user")),
        _cell(row, columns.get("proxy_password")),
    )


def _parse_proxy(row, columns):
    proxy_type, host, port_text, user, password = _proxy_values(row, columns)
    if not any((host, port_text, user, password)) and proxy_type in ("", "direct"):
        return {"proxy_type": "direct"}, None

    if proxy_type not in PROXY_TYPES:
        raise ValueError("proxy_type harus http, https, atau socks5")
    if not host:
        raise ValueError("proxy_ip wajib diisi bila proxy dipakai")
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        raise ValueError("proxy_port harus berupa angka 1 sampai 65535")
    if not 1 <= port <= 65535:
        raise ValueError("proxy_port harus 1 sampai 65535")

    config = {
        "proxy_type": proxy_type,
        "proxy_ip": host,
        "proxy_port": port,
        "proxy_user": user or None,
        "proxy_password": password or None,
    }
    key = (proxy_type, host.lower(), port, user)
    return config, key


def _parse_platform(row, columns):
    raw = _cell(row, columns.get("platform"))
    key = raw.lower() or "windows"
    if key not in PLATFORM_VERSIONS:
        raise ValueError("platform harus Windows atau Macos")
    platform, versions = PLATFORM_VERSIONS[key]

    version = _cell(row, columns.get("system_version"))
    if not version:
        version = versions[0]
    if version not in versions:
        raise ValueError(
            f"system_version {platform} harus salah satu dari {', '.join(versions)}"
        )
    return platform, version


def _site_url(row, columns):
    url = _cell(row, columns.get("site_url"))
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("site_url harus diawali http:// atau https://")
    return url


def _row_payload(row, columns):
    name = _cell(row, columns.get("name"))
    if not name:
        raise ValueError("name wajib diisi")
    if len(name) > 100:
        raise ValueError("name maksimal 100 karakter")

    note = _cell(row, columns.get("note"))
    if len(note) > 200:
        raise ValueError("note maksimal 200 karakter")

    platform, version = _parse_platform(row, columns)
    site_url = _site_url(row, columns)
    proxy_config, proxy_key = _parse_proxy(row, columns)
    return {
        "name": name,
        "group_title": _cell(row, columns.get("group")) or "Default",
        "note": note or None,
        "platform": platform,
        "system_version": version,
        "site_url": site_url,
        "proxy_config": proxy_config,
        "proxy_key": proxy_key,
    }


def _proxy_key(proxy_type, host, port, user):
    return (
        str(proxy_type or "").strip().lower(),
        str(host or "").strip().lower(),
        int(port) if port not in (None, "") else None,
        str(user or "").strip(),
    )


def _existing_proxies(conn):
    found = {}
    rows = conn.execute(
        "SELECT id, proxy_type, proxy_ip, proxy_port, proxy_user FROM proxies ORDER BY id"
    ).fetchall()
    for row in rows:
        key = _proxy_key(
            row["proxy_type"], row["proxy_ip"], row["proxy_port"], row["proxy_user"]
        )
        found.setdefault(key, row["id"])
    return found


def _group_id(conn, title):
    row = conn.execute(
        "SELECT id FROM groups WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
        (title,),
    ).fetchone()
    if row:
        return row["id"], False
    cur = conn.execute(
        "INSERT INTO groups (title, sort, created_at) VALUES (?, ?, ?)",
        (title, 0, store.now()),
    )
    conn.commit()
    return cur.lastrowid, True


def import_csv(text):
    if not isinstance(text, str):
        raise CsvImportError("isi CSV harus berupa teks")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CsvImportError("file CSV maksimal 1 MB")
    if not text.strip():
        raise CsvImportError("file CSV kosong")

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvImportError("file CSV kosong")

    normalized = [str(cell).lstrip("\ufeff").strip().lower() for cell in header]
    if "name" not in normalized:
        raise CsvImportError("header CSV wajib memuat kolom name")
    columns = {}
    for index, key in enumerate(normalized):
        if key not in columns:
            columns[key] = index

    entries = []
    for row in reader:
        if not row or all(not str(cell).strip() for cell in row):
            continue
        entries.append((reader.line_num, row))
        if len(entries) > MAX_ROWS:
            raise CsvImportError(f"maksimal {MAX_ROWS} baris data per impor")

    created = 0
    groups_created = 0
    proxies_created = 0
    errors = []
    profiles = []
    with store.db() as conn:
        known_proxies = _existing_proxies(conn)
        for line, row in entries:
            try:
                payload = _row_payload(row, columns)
            except ValueError as error:
                errors.append({"line": line, "message": str(error)})
                continue

            group_id, group_is_new = _group_id(conn, payload["group_title"])
            if group_is_new:
                groups_created += 1

            proxy_key = payload["proxy_key"]
            if proxy_key and proxy_key not in known_proxies:
                proxy_id = store.create_proxy(
                    conn,
                    {
                        **payload["proxy_config"],
                        "note": "Impor CSV",
                    },
                )
                known_proxies[proxy_key] = proxy_id
                proxies_created += 1

            profile_id = store.create_profile(
                conn,
                {
                    "name": payload["name"],
                    "group_id": group_id,
                    "note": payload["note"],
                    "site_url": payload["site_url"],
                    "proxy_config": payload["proxy_config"],
                    "fingerprint_config": {
                        "platform": payload["platform"],
                        "system_version": payload["system_version"],
                    },
                },
            )
            created += 1
            profiles.append({"profile_id": profile_id, "name": payload["name"]})

    return {
        "created": created,
        "groups_created": groups_created,
        "proxies_created": proxies_created,
        "errors": errors,
        "profiles": profiles,
    }
