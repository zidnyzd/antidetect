"""Read and write saved logins from a Chromium profile."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from . import cookies, launcher


class PasswordError(Exception):
    pass


def _profiles_dir():
    from . import paths, store

    if launcher.PROFILES_DIR != paths.DATA_DIR / "profiles":
        return launcher.PROFILES_DIR
    if Path(store.DB_PATH) != store._INITIAL_DB_PATH:
        return Path(store.DB_PATH).parent / "profiles"
    env_home = os.environ.get("ANTIDETECT_HOME")
    if env_home:
        return Path(env_home) / "profiles"
    return launcher.PROFILES_DIR


def _database_path(profile_id):
    base = _profiles_dir() / str(profile_id)
    candidates = (
        base / "data" / "Default" / "Login Data",
        base / "Default" / "Login Data",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _decrypt(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if not raw:
        return ""
    if raw[:3] in (b"v10", b"v11"):
        try:
            return cookies._cbc_decrypt(raw[3:]).decode("utf-8", "replace")
        except Exception:
            return ""
    return raw.decode("utf-8", "replace")


def _read_rows(path):
    conn = sqlite3.connect(path, timeout=0.5)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'logins'"
        ).fetchone():
            return []
        columns = {row[1] for row in conn.execute("PRAGMA table_info(logins)")}
        if "password_value" not in columns:
            return []
        if "origin_url" in columns:
            origin = "origin_url"
        elif "signon_realm" in columns:
            origin = "signon_realm"
        else:
            return []
        username = "username_value" if "username_value" in columns else "''"
        where = ""
        if "blacklisted_by_user" in columns:
            where = "WHERE COALESCE(blacklisted_by_user, 0) = 0"
        rows = conn.execute(
            f"SELECT {origin}, {username}, password_value FROM logins {where} ORDER BY {origin}, {username}"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "origin_url": str(origin_url or ""),
            "username": str(username_value or ""),
            "password": _decrypt(password_value),
        }
        for origin_url, username_value, password_value in rows
    ]


def _read_copy(path):
    """Snapshot the database so a running profile cannot block the read."""
    folder = Path(tempfile.mkdtemp(prefix="antidetect-login-"))
    try:
        copy = folder / path.name
        shutil.copy2(path, copy)
        for suffix in ("-wal", "-shm"):
            extra = path.with_name(path.name + suffix)
            if extra.is_file():
                try:
                    shutil.copy2(extra, folder / (path.name + suffix))
                except OSError:
                    pass
        return _read_rows(copy)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _read_snapshot(path):
    try:
        return _read_copy(path)
    except (OSError, sqlite3.DatabaseError) as error:
        raise PasswordError(f"gagal membaca password: {error}")


def list_saved_passwords(profile_id):
    path = _database_path(profile_id)
    if not path.is_file():
        return []
    if launcher.is_open(int(profile_id)):
        return _read_snapshot(path)
    try:
        return _read_rows(path)
    except sqlite3.OperationalError:
        return _read_snapshot(path)
    except sqlite3.DatabaseError as error:
        raise PasswordError(f"gagal membaca password: {error}")


def delete_password(profile_id, origin_url, username):
    profile_id = int(profile_id)
    if launcher.is_open(profile_id):
        raise PasswordError("tutup profil dulu")
    origin = str(origin_url or "")
    if not origin:
        raise PasswordError("origin_url wajib diisi")
    user = "" if username is None else str(username)

    path = _database_path(profile_id)
    if not path.is_file():
        raise PasswordError("password tidak ditemukan")
    try:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    except OSError as error:
        raise PasswordError(f"gagal membuat backup password: {error}")

    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(logins)")}
            if "origin_url" not in columns or "username_value" not in columns:
                raise PasswordError("password tidak ditemukan")
            cursor = conn.execute(
                "DELETE FROM logins WHERE origin_url = ? AND username_value = ?",
                (origin, user),
            )
            conn.commit()
            deleted = cursor.rowcount
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        raise PasswordError(f"gagal menghapus password: {error}")

    if deleted <= 0:
        raise PasswordError("password tidak ditemukan")
    return {"deleted": deleted}


_LOGIN_DATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR);
INSERT OR IGNORE INTO meta (key, value) VALUES ('version', '40'), ('last_compatible_version', '40');
CREATE TABLE IF NOT EXISTS logins (
    origin_url VARCHAR NOT NULL,
    action_url VARCHAR,
    username_element VARCHAR,
    username_value VARCHAR,
    password_element VARCHAR,
    password_value BLOB,
    submit_element VARCHAR,
    signon_realm VARCHAR NOT NULL,
    date_created INTEGER NOT NULL,
    blacklisted_by_user INTEGER NOT NULL DEFAULT 0,
    scheme INTEGER NOT NULL DEFAULT 0,
    password_type INTEGER DEFAULT 0,
    times_used INTEGER DEFAULT 0,
    form_data BLOB,
    date_synced INTEGER DEFAULT 0,
    display_name VARCHAR,
    icon_url VARCHAR,
    federation_url VARCHAR,
    skip_zero_click INTEGER DEFAULT 0,
    generation_upload_status INTEGER DEFAULT 0,
    possible_username_pairs BLOB,
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_last_used INTEGER DEFAULT 0,
    moving_blocked_for BLOB,
    date_password_modified INTEGER DEFAULT 0,
    sender_email VARCHAR,
    sender_name VARCHAR,
    date_received INTEGER DEFAULT 0,
    sharing_notification_displayed INTEGER DEFAULT 0,
    keychain_identifier VARCHAR
);
"""


def _normalize_password_items(items):
    if items is None:
        return []
    if isinstance(items, (bytes, bytearray)):
        text = items.decode("utf-8").strip()
        items = json.loads(text) if text else []
    elif isinstance(items, str):
        text = items.strip()
        items = json.loads(text) if text else []
    if isinstance(items, dict) and "passwords" in items:
        items = items["passwords"]
    if not isinstance(items, list):
        raise PasswordError("format password harus berupa list")
    return items


def update_passwords(profile_id, items):
    profile_id = int(profile_id)
    if launcher.is_open(profile_id):
        raise PasswordError("tutup profil dulu")
    rows = _normalize_password_items(items)
    path = _database_path(profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass

    now_chrome = int((time.time() + cookies._EPOCH_DELTA) * 1_000_000)
    written = 0
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.executescript(_LOGIN_DATA_SCHEMA)
            for item in rows:
                if not isinstance(item, dict):
                    continue
                origin_url = str(item.get("origin_url") or "")
                username = str(
                    item.get("username")
                    if item.get("username") is not None
                    else (item.get("username_value") or "")
                )
                pwd_raw = str(
                    item.get("password") if item.get("password") is not None else ""
                )
                signon_realm = str(item.get("signon_realm") or origin_url)
                action_url = str(item.get("action_url") or origin_url)
                encrypted = b"v10" + cookies._cbc_encrypt(pwd_raw.encode("utf-8"))
                conn.execute(
                    "DELETE FROM logins WHERE origin_url = ? AND username_value = ?",
                    (origin_url, username),
                )
                conn.execute(
                    """INSERT INTO logins (
                           origin_url, action_url, username_element, username_value,
                           password_element, password_value, submit_element, signon_realm,
                           date_created, blacklisted_by_user, scheme
                       ) VALUES (?, ?, '', ?, '', ?, '', ?, ?, 0, 0)""",
                    (
                        origin_url,
                        action_url,
                        username,
                        encrypted,
                        signon_realm,
                        now_chrome,
                    ),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        raise PasswordError(f"gagal menulis password: {error}") from error
    return written


def password_digest(items):
    if isinstance(items, int):
        rows = list_saved_passwords(items)
    elif isinstance(items, str) and items.strip().isdigit():
        rows = list_saved_passwords(int(items.strip()))
    else:
        rows = _normalize_password_items(items)

    normalized = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        origin_url = str(item.get("origin_url") or "")
        username = str(
            item.get("username")
            if item.get("username") is not None
            else (item.get("username_value") or "")
        )
        password = str(
            item.get("password") if item.get("password") is not None else ""
        )
        normalized.append(
            {
                "origin_url": origin_url,
                "username": username,
                "password": password,
            }
        )
    normalized.sort(key=lambda x: (x["origin_url"], x["username"], x["password"]))
    canonical_json_bytes = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_json_bytes).hexdigest()

