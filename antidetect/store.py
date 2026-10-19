"""SQLite storage for profiles, groups, tags and proxies."""
import json
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager

from . import launcher
from .paths import DATA_DIR

DB_PATH = DATA_DIR / "antidetect.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    group_id INTEGER NOT NULL DEFAULT 1,
    color TEXT,
    note TEXT,
    site_id INTEGER,
    site_url TEXT,
    proxy_config TEXT,
    fingerprint_config TEXT,
    preference_config TEXT,
    tag_ids TEXT DEFAULT '[]',
    last_open_time INTEGER,
    seed INTEGER,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_type TEXT,
    proxy_ip TEXT,
    proxy_port INTEGER,
    proxy_user TEXT,
    proxy_password TEXT,
    note TEXT,
    tag TEXT
);
"""


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init():
    with db() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
        if "tag_ids" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN tag_ids TEXT DEFAULT '[]'")
        if "last_open_time" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN last_open_time INTEGER")
        group_columns = {row["name"] for row in conn.execute("PRAGMA table_info(groups)")}
        if "created_at" not in group_columns:
            conn.execute("ALTER TABLE groups ADD COLUMN created_at TEXT")
        if not conn.execute("SELECT 1 FROM groups LIMIT 1").fetchone():
            conn.execute("INSERT INTO groups (title, sort) VALUES ('Default', 0)")
        conn.commit()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _loads(value):
    try:
        return json.loads(value) if value else {}
    except ValueError:
        return {}


def _load_list(value):
    try:
        data = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _int_list(value):
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def profile_to_dict(row, include_seed=False):
    data = {
        "profile_id": row["id"],
        "name": row["name"],
        "group_id": row["group_id"],
        "color": row["color"],
        "note": row["note"],
        "site_id": row["site_id"],
        "site_url": row["site_url"],
        "proxy_config": _loads(row["proxy_config"]),
        "fingerprint_config": _loads(row["fingerprint_config"]),
        "preference_config": _loads(row["preference_config"]),
        "tab_id": _load_list(row["tag_ids"]),
        "last_open_time": row["last_open_time"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_seed:
        data["seed"] = row["seed"]
    return data


def profile_get(conn, profile_id):
    return conn.execute("SELECT * FROM profiles WHERE id = ?", (int(profile_id),)).fetchone()


def list_profiles(conn, page=1, limit=10, group_id=None, name=None, profile_id=None):
    clauses, args = [], []
    if profile_id:
        clauses.append("id = ?")
        args.append(int(profile_id))
    if group_id:
        clauses.append("group_id = ?")
        args.append(int(group_id))
    if name:
        clauses.append("name LIKE ?")
        args.append(f"%{name}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM profiles {where}", args).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM profiles {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, int(limit), (int(page) - 1) * int(limit)],
    ).fetchall()
    return total, rows


def create_profile(conn, data):
    ts = now()
    tag_ids = _int_list(data.get("tab_id", data.get("tag_ids")))
    cur = conn.execute(
        """INSERT INTO profiles
           (name, group_id, color, note, site_id, site_url,
            proxy_config, fingerprint_config, preference_config, tag_ids, seed, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("name") or "Profile",
            data.get("group_id") or 1,
            data.get("color"),
            data.get("note"),
            data.get("site_id") if data.get("site_id") is not None else 22,
            data.get("site_url"),
            json.dumps(data.get("proxy_config") or {}),
            json.dumps(data.get("fingerprint_config") or {}),
            json.dumps(data.get("preference_config") or {}),
            json.dumps(tag_ids),
            int(data.get("seed") or secrets.randbelow(2**31 - 1) + 1),
            ts,
            ts,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_profile(conn, profile_id, data):
    fields, args = [], []
    for key in ("name", "group_id", "color", "note", "site_id", "site_url"):
        if key in data:
            fields.append(f"{key} = ?")
            args.append(data[key])
    for key in ("proxy_config", "fingerprint_config", "preference_config"):
        if data.get(key) is not None:
            fields.append(f"{key} = ?")
            args.append(json.dumps(data[key]))
    tag_source = next((key for key in ("tab_id", "tag_id", "tag_ids") if key in data), None)
    if tag_source:
        fields.append("tag_ids = ?")
        args.append(json.dumps(_int_list(data[tag_source])))
    if data.get("seed"):
        fields.append("seed = ?")
        args.append(int(data["seed"]))
    if not fields:
        return
    fields.append("updated_at = ?")
    args.extend([now(), int(profile_id)])
    conn.execute(f"UPDATE profiles SET {', '.join(fields)} WHERE id = ?", args)
    conn.commit()


def mark_opened(conn, profile_id, timestamp=None):
    conn.execute(
        "UPDATE profiles SET last_open_time = ? WHERE id = ?",
        (int(timestamp or time.time()), int(profile_id)),
    )
    conn.commit()


def delete_profile(conn, profile_id):
    conn.execute("DELETE FROM profiles WHERE id = ?", (int(profile_id),))
    conn.commit()
    shutil.rmtree(launcher.PROFILES_DIR / str(profile_id), ignore_errors=True)


def latest_seed(conn, profile_id):
    row = profile_get(conn, profile_id)
    return row["seed"] if row else None
