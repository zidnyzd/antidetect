"""SQLite storage for profiles, groups, tags and proxies."""
import datetime
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
    updated_at TEXT,
    deleted_at TEXT
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
CREATE TABLE IF NOT EXISTS extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    title TEXT,
    version TEXT,
    path TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    profile_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);
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
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN deleted_at TEXT")
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


def profile_to_dict(row, include_seed=True):
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
        "deleted_at": row["deleted_at"],
    }
    if include_seed:
        data["seed"] = row["seed"]
    return data


def profile_get(conn, profile_id):
    return conn.execute("SELECT * FROM profiles WHERE id = ?", (int(profile_id),)).fetchone()


PROFILE_SORT_FIELDS = ("name", "group", "last_open", "created")
PROFILE_SORT_DIRS = ("asc", "desc")


def list_profiles(conn, page=1, limit=10, group_id=None, name=None, profile_id=None, deleted=False,
                  tag_id=None, sort_by="created", sort_dir="desc"):
    sort_by = str(sort_by or "created").strip()
    sort_dir = str(sort_dir or "desc").strip().lower()
    if sort_by not in PROFILE_SORT_FIELDS:
        raise ValueError(
            f"sort_by tidak valid, pilih salah satu dari {', '.join(PROFILE_SORT_FIELDS)}"
        )
    if sort_dir not in PROFILE_SORT_DIRS:
        raise ValueError("sort_dir tidak valid, pilih asc atau desc")

    clauses, args = [], []
    clauses.append("p.deleted_at IS NOT NULL" if deleted else "p.deleted_at IS NULL")
    if profile_id:
        clauses.append("p.id = ?")
        args.append(int(profile_id))
    if group_id:
        clauses.append("p.group_id = ?")
        args.append(int(group_id))
    if tag_id not in (None, "", 0, "0"):
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(p.tag_ids) WHERE json_each.value = ?)"
        )
        args.append(int(tag_id))
    if name:
        clauses.append("p.name LIKE ?")
        args.append(f"%{name}%")
    where = f"WHERE {' AND '.join(clauses)}"
    join = "LEFT JOIN groups g ON g.id = p.group_id" if sort_by == "group" else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM profiles p {join} {where}", args
    ).fetchone()["c"]

    if deleted:
        order = "p.deleted_at DESC, p.id DESC"
    else:
        direction = "ASC" if sort_dir == "asc" else "DESC"
        tie = "ASC" if sort_dir == "asc" else "DESC"
        if sort_by == "last_open":
            # Profil yang belum pernah dibuka selalu di akhir.
            order = (
                f"p.last_open_time IS NULL ASC, "
                f"p.last_open_time {direction}, p.id {tie}"
            )
        else:
            column = {
                "name": "p.name COLLATE NOCASE",
                "group": "COALESCE(g.title, 'Default') COLLATE NOCASE",
                "created": "p.created_at",
            }[sort_by]
            order = f"{column} {direction}, p.id {tie}"
    rows = conn.execute(
        f"SELECT p.* FROM profiles p {join} {where} ORDER BY {order} LIMIT ? OFFSET ?",
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
    """Permanent delete, retained for the CLI."""
    delete_profile_permanent(conn, profile_id)


def soft_delete_profile(conn, profile_id):
    conn.execute(
        "UPDATE profiles SET deleted_at = ? WHERE id = ?",
        (now(), int(profile_id)),
    )
    conn.commit()


def restore_profile(conn, profile_id):
    conn.execute("UPDATE profiles SET deleted_at = NULL WHERE id = ?", (int(profile_id),))
    conn.commit()


def delete_profile_permanent(conn, profile_id):
    conn.execute("DELETE FROM profiles WHERE id = ?", (int(profile_id),))
    conn.commit()
    shutil.rmtree(launcher.PROFILES_DIR / str(profile_id), ignore_errors=True)


def empty_recycle_bin(conn):
    rows = conn.execute("SELECT id FROM profiles WHERE deleted_at IS NOT NULL").fetchall()
    for row in rows:
        delete_profile_permanent(conn, row["id"])
    return len(rows)


def latest_seed(conn, profile_id):
    row = profile_get(conn, profile_id)
    return row["seed"] if row else None


def create_proxy(conn, data):
    cur = conn.execute(
        """INSERT INTO proxies (proxy_type, proxy_ip, proxy_port, proxy_user,
           proxy_password, note, tag) VALUES (?,?,?,?,?,?,?)""",
        (
            data.get("proxy_type"),
            data.get("proxy_ip"),
            data.get("proxy_port"),
            data.get("proxy_user"),
            data.get("proxy_password"),
            data.get("note"),
            data.get("tag"),
        ),
    )
    conn.commit()
    return cur.lastrowid


EVENT_LIMIT = 2000
EVENT_GROUPS = ("profile", "proxy", "extension", "group", "tag")


def add_event(conn, kind, message, profile_id=None):
    conn.execute(
        "INSERT INTO events (kind, message, profile_id, created_at) VALUES (?,?,?,?)",
        (str(kind), str(message), None if profile_id is None else int(profile_id), now()),
    )
    conn.execute(
        "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
        (EVENT_LIMIT,),
    )
    conn.commit()


def list_events(conn, page=1, limit=20, kind=None, start=None, end=None, q=None):
    clauses, args = [], []
    kind = str(kind or "").strip()
    if kind in EVENT_GROUPS:
        clauses.append("e.kind LIKE ?")
        args.append(f"{kind}-%")
    elif kind == "system":
        for group in EVENT_GROUPS:
            clauses.append("e.kind NOT LIKE ?")
            args.append(f"{group}-%")
    elif kind:
        clauses.append("e.kind = ?")
        args.append(kind)
    if start:
        clauses.append("e.created_at >= ?")
        args.append(start)
    if end:
        clauses.append("e.created_at <= ?")
        args.append(end)
    needle = str(q or "").strip()
    if needle:
        clauses.append("(e.message LIKE ? OR COALESCE(p.name, '') LIKE ?)")
        args.extend([f"%{needle}%", f"%{needle}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, int(limit))
    page = max(1, int(page))
    join = "LEFT JOIN profiles p ON p.id = e.profile_id"
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM events e {join} {where}", args
    ).fetchone()["c"]
    rows = conn.execute(
        f"""SELECT e.id, e.kind, e.message, e.profile_id, e.created_at,
                   p.name AS profile_name
            FROM events e
            {join}
            {where}
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ? OFFSET ?""",
        [*args, limit, (page - 1) * limit],
    ).fetchall()
    return total, rows


def parse_event_range(start=None, end=None):
    """Normalize a local ISO date/datetime range to created_at text bounds."""
    start_text = _event_time(start, end_of_day=False)
    end_text = _event_time(end, end_of_day=True)
    if start_text and end_text and start_text > end_text:
        raise ValueError("start tidak boleh lebih besar dari end")
    return start_text, end_text


def _event_time(value, end_of_day):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            day = datetime.date.fromisoformat(text)
            clock = datetime.time(23, 59, 59) if end_of_day else datetime.time(0, 0, 0)
            moment = datetime.datetime.combine(day, clock)
        else:
            moment = datetime.datetime.fromisoformat(text.replace("T", " ", 1))
    except ValueError:
        raise ValueError("waktu harus berformat YYYY-MM-DD atau datetime lokal")
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _csv_cell(value):
    text = "" if value is None else str(value)
    if any(char in text for char in (",", '"', "\r", "\n")):
        return '"' + text.replace('"', '""') + '"'
    return text


def events_csv(rows):
    lines = ["id,waktu,jenis,profil_id,pesan"]
    for row in rows:
        lines.append(
            ",".join(
                _csv_cell(value)
                for value in (
                    row["id"],
                    row["created_at"],
                    row["kind"],
                    row["profile_id"],
                    row["message"],
                )
            )
        )
    return "\r\n".join(lines) + "\r\n"



def clear_events(conn):
    cur = conn.execute("DELETE FROM events")
    conn.commit()
    return cur.rowcount
