"""Read saved logins from a Chromium profile."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import cookies, launcher


class PasswordError(Exception):
    pass


def _database_path(profile_id):
    base = launcher.PROFILES_DIR / str(profile_id)
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
            f"SELECT {origin}, {username}, password_value FROM logins {where} ORDER BY {origin}"
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
