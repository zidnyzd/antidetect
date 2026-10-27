"""SQLite storage for profiles, groups, tags and proxies."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import launcher, sync_crypto
from .paths import DATA_DIR

_INITIAL_DB_PATH = DATA_DIR / "antidetect.db"
DB_PATH = _INITIAL_DB_PATH

DEFAULT_GROUP_UUID = "00000000-0000-4000-8000-000000000001"
GROUP_UUID_NS = uuid.UUID("00000000-0000-4000-8000-000000000010")
TAG_UUID_NS = uuid.UUID("00000000-0000-4000-8000-000000000020")

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
    proxy_key TEXT,
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
CREATE TABLE IF NOT EXISTS proxy_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_id INTEGER,
    checked_at TEXT,
    ok INTEGER,
    ip TEXT,
    latency_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_proxy_checks_proxy ON proxy_checks (proxy_id, checked_at);
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    payload TEXT,
    created_at TEXT
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

SYNC_TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    entity_uuid TEXT NOT NULL,
    operation TEXT NOT NULL,
    base_revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    blob_path TEXT,
    fencing_token INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_retry ON sync_outbox (next_retry_at, outbox_id);
CREATE TABLE IF NOT EXISTS local_leases (
    profile_uuid TEXT PRIMARY KEY,
    holder_device_id TEXT NOT NULL,
    holder_device_name TEXT,
    lease_token TEXT,
    fencing_token INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    is_local_holder INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS local_conflicts (
    conflict_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_uuid TEXT NOT NULL,
    reason TEXT NOT NULL,
    losing_payload TEXT NOT NULL,
    winning_payload TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _resolve_db_path(db_path=None):
    if db_path is not None:
        candidate = Path(db_path)
        if candidate.is_dir():
            return candidate / "antidetect.db"
        return candidate
    if Path(DB_PATH) != _INITIAL_DB_PATH:
        return Path(DB_PATH)
    env_home = os.environ.get("ANTIDETECT_HOME")
    if env_home:
        return Path(env_home) / "antidetect.db"
    return Path(DB_PATH)


def _conn_db_path(conn):
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        for row in rows:
            name = row[1] if isinstance(row, tuple) else row["name"]
            file_path = row[2] if isinstance(row, tuple) else row["file"]
            if name == "main" and file_path:
                return Path(file_path)
    except Exception:
        pass
    return _resolve_db_path()


def connect(db_path=None):
    target = _resolve_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db(db_path=None):
    conn = connect(db_path=db_path)
    try:
        yield conn
    finally:
        conn.close()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def group_uuid_for_title(title, group_id=None):
    norm = str(title or "").strip().lower()
    if group_id == 1 or norm in ("", "default"):
        return DEFAULT_GROUP_UUID
    return str(uuid.uuid5(GROUP_UUID_NS, norm))


def tag_uuid_for_title(title):
    norm = str(title or "").strip().lower()
    return str(uuid.uuid5(TAG_UUID_NS, norm or "tag"))


def _unique_entity_uuid(conn, table, candidate_uuid, exclude_id=None):
    if not candidate_uuid:
        candidate_uuid = str(uuid.uuid4())
    if exclude_id is None:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE uuid = ? LIMIT 1", (candidate_uuid,)
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE uuid = ? AND id <> ? LIMIT 1",
            (candidate_uuid, int(exclude_id)),
        ).fetchone()
    if not row:
        return candidate_uuid
    return str(uuid.uuid4())


def get_sync_state(conn, key, default=None):
    try:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (str(key),)
        ).fetchone()
        return row["value"] if row else default
    except sqlite3.OperationalError:
        return default


def set_sync_state(conn, key, value):
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(key), str(value)),
    )


def get_device_id(conn):
    dev_id = get_sync_state(conn, "device_id")
    if dev_id:
        return dev_id
    dev_id = str(uuid.uuid4())
    try:
        set_sync_state(conn, "device_id", dev_id)
    except sqlite3.OperationalError:
        pass
    return dev_id


def _load_local_crypto(conn):
    creds_path = _conn_db_path(conn).parent / "sync_credentials.json"
    if not creds_path.is_file():
        return None, None
    try:
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        kek_hex = data.get("kek_hex")
        dedupe_hex = data.get("dedupe_key_hex")
        if kek_hex:
            kek = bytes.fromhex(kek_hex)
            dedupe = (
                bytes.fromhex(dedupe_hex)
                if dedupe_hex
                else sync_crypto.derive_dedupe_key(kek)
            )
            return kek, dedupe
    except Exception:
        pass
    return None, None


def _ensure_sync_schema(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
    if "uuid" not in columns:
        conn.commit()
        db_file = _conn_db_path(conn)
        if db_file.is_file():
            ts_bak = time.strftime("%Y%m%d-%H%M%S")
            bak_path = db_file.parent / f"{db_file.name}.pre-sync-{ts_bak}.bak"
            bak_conn = sqlite3.connect(str(bak_path))
            try:
                conn.backup(bak_conn)
            finally:
                bak_conn.close()

    profile_additions = [
        ("uuid", "TEXT"),
        ("revision", "INTEGER NOT NULL DEFAULT 0"),
        ("origin_device", "TEXT"),
        ("purged_at", "TEXT"),
        ("cookie_blob_id", "TEXT"),
        ("cookie_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("cookie_sha256", "TEXT"),
        ("bookmark_blob_id", "TEXT"),
        ("bookmark_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("bookmark_sha256", "TEXT"),
        ("password_blob_id", "TEXT"),
        ("password_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("password_sha256", "TEXT"),
        ("sync_dirty", "INTEGER NOT NULL DEFAULT 1"),
    ]
    for col_name, col_def in profile_additions:
        if col_name not in columns:
            conn.execute(f"ALTER TABLE profiles ADD COLUMN {col_name} {col_def}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_uuid ON profiles (uuid)")

    entity_additions = [
        ("uuid", "TEXT"),
        ("revision", "INTEGER NOT NULL DEFAULT 0"),
        ("deleted_at", "TEXT"),
        ("origin_device", "TEXT"),
        ("sync_dirty", "INTEGER NOT NULL DEFAULT 1"),
    ]
    for table in ("groups", "tags", "proxies", "templates", "extensions"):
        t_cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col_name, col_def in entity_additions:
            if col_name not in t_cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        if table == "extensions":
            for col_name, col_def in (
                ("archive_blob_id", "TEXT"),
                ("archive_sha256", "TEXT"),
            ):
                if col_name not in t_cols:
                    conn.execute(
                        f"ALTER TABLE extensions ADD COLUMN {col_name} {col_def}"
                    )
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uuid ON {table} (uuid)"
        )

    conn.executescript(SYNC_TABLES_SCHEMA)

    if not get_sync_state(conn, "device_id"):
        set_sync_state(conn, "device_id", str(uuid.uuid4()))
    if not get_sync_state(conn, "device_name"):
        set_sync_state(conn, "device_name", socket.gethostname() or "Device")
    if get_sync_state(conn, "last_pulled_seq") is None:
        set_sync_state(conn, "last_pulled_seq", "0")


def _backfill_uuids(conn):
    device_id = get_device_id(conn)

    group_rows = conn.execute(
        "SELECT id, title, uuid FROM groups ORDER BY id"
    ).fetchall()
    for row in group_rows:
        if not row["uuid"]:
            is_default = row["id"] == 1 or str(row["title"] or "").strip().lower() == "default"
            target_uuid = (
                DEFAULT_GROUP_UUID
                if is_default
                else group_uuid_for_title(row["title"], row["id"])
            )
            target_uuid = _unique_entity_uuid(
                conn, "groups", target_uuid, exclude_id=row["id"]
            )
            dirty = 0 if is_default else 1
            conn.execute(
                "UPDATE groups SET uuid = ?, origin_device = COALESCE(origin_device, ?), sync_dirty = ? WHERE id = ?",
                (target_uuid, device_id, dirty, row["id"]),
            )

    tag_rows = conn.execute("SELECT id, title, uuid FROM tags ORDER BY id").fetchall()
    for row in tag_rows:
        if not row["uuid"]:
            target_uuid = _unique_entity_uuid(
                conn, "tags", tag_uuid_for_title(row["title"]), exclude_id=row["id"]
            )
            conn.execute(
                "UPDATE tags SET uuid = ?, origin_device = COALESCE(origin_device, ?), sync_dirty = 1 WHERE id = ?",
                (target_uuid, device_id, row["id"]),
            )

    for table in ("proxies", "templates", "extensions"):
        rows = conn.execute(f"SELECT id, uuid FROM {table} ORDER BY id").fetchall()
        for row in rows:
            if not row["uuid"]:
                target_uuid = _unique_entity_uuid(
                    conn, table, str(uuid.uuid4()), exclude_id=row["id"]
                )
                conn.execute(
                    f"UPDATE {table} SET uuid = ?, origin_device = COALESCE(origin_device, ?), sync_dirty = 1 WHERE id = ?",
                    (target_uuid, device_id, row["id"]),
                )

    profile_rows = conn.execute(
        "SELECT id, uuid FROM profiles ORDER BY id"
    ).fetchall()
    for row in profile_rows:
        if not row["uuid"]:
            target_uuid = _unique_entity_uuid(
                conn, "profiles", str(uuid.uuid4()), exclude_id=row["id"]
            )
            conn.execute(
                """UPDATE profiles
                   SET uuid = ?,
                       revision = COALESCE(revision, 0),
                       origin_device = COALESCE(origin_device, ?),
                       sync_dirty = 1
                   WHERE id = ?""",
                (target_uuid, device_id, row["id"]),
            )


def init(db_path=None):
    with db(db_path=db_path) as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
        if "tag_ids" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN tag_ids TEXT DEFAULT '[]'")
        if "last_open_time" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN last_open_time INTEGER")
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN deleted_at TEXT")
        if "proxy_key" not in columns:
            conn.execute("ALTER TABLE profiles ADD COLUMN proxy_key TEXT")
        group_columns = {row["name"] for row in conn.execute("PRAGMA table_info(groups)")}
        if "created_at" not in group_columns:
            conn.execute("ALTER TABLE groups ADD COLUMN created_at TEXT")
        if not conn.execute("SELECT 1 FROM groups LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO groups (title, sort, created_at) VALUES ('Default', 0, ?)",
                (now(),),
            )
        _ensure_sync_schema(conn)
        _backfill_uuids(conn)
        conn.commit()


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


def proxy_key_for(proxy_config):
    """MD5 of ip+port+user+password, as ixBrowser computes it.

    Only a real proxy has a key; direct and traffic-package modes do not.
    """
    if not isinstance(proxy_config, dict):
        return None
    proxy_type = str(proxy_config.get("proxy_type") or "direct").strip().lower()
    if proxy_type in ("", "direct", "none"):
        return None
    mode = proxy_config.get("proxy_mode")
    if mode is not None and str(mode).strip() == "1":
        return None
    parts = [
        str(proxy_config.get("proxy_ip") or ""),
        str(proxy_config.get("proxy_port") or ""),
        str(proxy_config.get("proxy_user") or ""),
        str(proxy_config.get("proxy_password") or ""),
    ]
    return hashlib.md5("".join(parts).encode("utf-8")).hexdigest()


def profile_to_dict(row, include_seed=True):
    proxy_config = _loads(row["proxy_config"])
    data = {
        "profile_id": row["id"],
        "uuid": _row_val(row, "uuid"),
        "name": row["name"],
        "group_id": row["group_id"],
        "color": row["color"],
        "note": row["note"],
        "site_id": row["site_id"],
        "site_url": row["site_url"],
        "proxy_config": proxy_config,
        "proxy_key": row["proxy_key"] if "proxy_key" in row.keys() else None
        or proxy_key_for(proxy_config),
        "fingerprint_config": _loads(row["fingerprint_config"]),
        "preference_config": _loads(row["preference_config"]),
        "tab_id": _load_list(row["tag_ids"]),
        "last_open_time": row["last_open_time"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
        "cookie_blob_id": _row_val(row, "cookie_blob_id"),
        "cookie_revision": int(_row_val(row, "cookie_revision") or 0),
        "bookmark_blob_id": _row_val(row, "bookmark_blob_id"),
        "bookmark_revision": int(_row_val(row, "bookmark_revision") or 0),
        "password_blob_id": _row_val(row, "password_blob_id"),
        "password_revision": int(_row_val(row, "password_revision") or 0),
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


def _row_val(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if key in row.keys() else default
    except Exception:
        return default


def _enqueue_outbox(conn, entity_type, entity_uuid, operation, payload, base_revision=0):
    if not entity_uuid:
        entity_uuid = str(uuid.uuid4())
    if isinstance(payload, str):
        payload_dict = _loads(payload)
    elif isinstance(payload, dict):
        payload_dict = dict(payload)
    else:
        payload_dict = {}

    ts = now_utc()
    if "updated_at" not in payload_dict or not payload_dict["updated_at"]:
        payload_dict["updated_at"] = ts

    try:
        conn.execute("SELECT 1 FROM sync_outbox LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        _ensure_sync_schema(conn)
        _backfill_uuids(conn)

    if operation == "purge":
        first_row = conn.execute(
            """SELECT base_revision FROM sync_outbox
               WHERE entity_type = ? AND entity_uuid = ?
               ORDER BY outbox_id ASC LIMIT 1""",
            (entity_type, entity_uuid),
        ).fetchone()
        eff_base = int(first_row["base_revision"]) if first_row else int(base_revision or 0)
        conn.execute(
            "DELETE FROM sync_outbox WHERE entity_type = ? AND entity_uuid = ?",
            (entity_type, entity_uuid),
        )
        conn.execute(
            """INSERT INTO sync_outbox
               (idempotency_key, entity_type, entity_uuid, operation,
                base_revision, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                entity_type,
                entity_uuid,
                "purge",
                eff_base,
                json.dumps(payload_dict, ensure_ascii=False),
                ts,
            ),
        )
        return

    last_row = conn.execute(
        """SELECT outbox_id, operation, base_revision, payload
           FROM sync_outbox
           WHERE entity_type = ? AND entity_uuid = ?
           ORDER BY outbox_id DESC LIMIT 1""",
        (entity_type, entity_uuid),
    ).fetchone()

    if last_row and last_row["operation"] == "upsert" and operation == "upsert":
        old_payload = _loads(last_row["payload"])
        merged_payload = {**old_payload, **payload_dict}
        conn.execute(
            """UPDATE sync_outbox
               SET idempotency_key = ?,
                   payload = ?,
                   created_at = ?,
                   attempts = 0,
                   next_retry_at = 0,
                   last_error = NULL
               WHERE outbox_id = ?""",
            (
                str(uuid.uuid4()),
                json.dumps(merged_payload, ensure_ascii=False),
                ts,
                last_row["outbox_id"],
            ),
        )
        return

    conn.execute(
        """INSERT INTO sync_outbox
           (idempotency_key, entity_type, entity_uuid, operation,
            base_revision, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            entity_type,
            entity_uuid,
            operation,
            int(base_revision or 0),
            json.dumps(payload_dict, ensure_ascii=False),
            ts,
        ),
    )


def _group_sync_payload(row, deleted_at=None):
    ts = now_utc()
    return {
        "uuid": _row_val(row, "uuid") or group_uuid_for_title(_row_val(row, "title"), _row_val(row, "id")),
        "title": _row_val(row, "title") or "Group",
        "sort": int(_row_val(row, "sort") or 0),
        "created_at": _row_val(row, "created_at") or ts,
        "updated_at": ts,
        "deleted_at": deleted_at if deleted_at is not None else _row_val(row, "deleted_at"),
    }


def _tag_sync_payload(row, deleted_at=None):
    ts = now_utc()
    return {
        "uuid": _row_val(row, "uuid") or tag_uuid_for_title(_row_val(row, "title")),
        "title": _row_val(row, "title") or "Tag",
        "created_at": ts,
        "updated_at": ts,
        "deleted_at": deleted_at if deleted_at is not None else _row_val(row, "deleted_at"),
    }


def _proxy_sync_payload(conn, row, deleted_at=None):
    ts = now_utc()
    kek, dedupe_key = _load_local_crypto(conn)
    raw_proxy = {
        "proxy_type": _row_val(row, "proxy_type"),
        "proxy_ip": _row_val(row, "proxy_ip"),
        "proxy_port": _row_val(row, "proxy_port"),
        "proxy_user": _row_val(row, "proxy_user"),
        "proxy_password": _row_val(row, "proxy_password"),
    }
    fp = sync_crypto.proxy_fingerprint(raw_proxy, dedupe_key) if dedupe_key else None
    enc_proxy = sync_crypto.encrypt_proxy_config(raw_proxy, kek) if kek else dict(raw_proxy)
    out = {
        "uuid": _row_val(row, "uuid"),
        "proxy_type": enc_proxy.get("proxy_type"),
        "proxy_ip": enc_proxy.get("proxy_ip"),
        "proxy_port": enc_proxy.get("proxy_port"),
        "proxy_user": enc_proxy.get("proxy_user"),
        "proxy_password_enc": enc_proxy.get("proxy_password_enc"),
        "proxy_fingerprint": fp,
        "note": _row_val(row, "note"),
        "tag": _row_val(row, "tag"),
        "created_at": ts,
        "updated_at": ts,
        "deleted_at": deleted_at if deleted_at is not None else _row_val(row, "deleted_at"),
    }
    if not kek and _row_val(row, "proxy_password") not in (None, ""):
        out["proxy_password"] = _row_val(row, "proxy_password")
    return out


def _template_sync_payload(row, deleted_at=None):
    ts = now_utc()
    return {
        "uuid": _row_val(row, "uuid"),
        "name": _row_val(row, "name") or "Template",
        "payload": _loads(_row_val(row, "payload")),
        "created_at": _row_val(row, "created_at") or ts,
        "updated_at": ts,
        "deleted_at": deleted_at if deleted_at is not None else _row_val(row, "deleted_at"),
    }


def _extension_sync_payload(row, deleted_at=None):
    ts = now_utc()
    return {
        "uuid": _row_val(row, "uuid"),
        "slug": _row_val(row, "slug"),
        "title": _row_val(row, "title"),
        "version": _row_val(row, "version"),
        "archive_blob_id": _row_val(row, "archive_blob_id"),
        "archive_sha256": _row_val(row, "archive_sha256"),
        "created_at": _row_val(row, "created_at") or ts,
        "updated_at": ts,
        "deleted_at": deleted_at if deleted_at is not None else _row_val(row, "deleted_at"),
    }


def _profile_sync_payload(conn, row):
    ts = now_utc()
    group_id = int(_row_val(row, "group_id") or 1)
    group_row = conn.execute(
        "SELECT id, title, uuid FROM groups WHERE id = ?", (group_id,)
    ).fetchone()
    if group_row:
        group_title = group_row["title"]
        group_uuid = _row_val(group_row, "uuid")
        if not group_uuid:
            group_uuid = _unique_entity_uuid(
                conn,
                "groups",
                group_uuid_for_title(group_title, group_row["id"]),
                exclude_id=group_row["id"],
            )
            conn.execute(
                "UPDATE groups SET uuid = ? WHERE id = ?", (group_uuid, group_row["id"])
            )
    else:
        group_title = "Default"
        group_uuid = DEFAULT_GROUP_UUID

    tag_ids = _int_list(_load_list(_row_val(row, "tag_ids")))
    tag_uuids = []
    tag_titles = {}
    for tid in tag_ids:
        t_row = conn.execute(
            "SELECT id, title, uuid FROM tags WHERE id = ?", (tid,)
        ).fetchone()
        if not t_row:
            continue
        t_uuid = _row_val(t_row, "uuid")
        if not t_uuid:
            t_uuid = _unique_entity_uuid(
                conn, "tags", tag_uuid_for_title(t_row["title"]), exclude_id=t_row["id"]
            )
            conn.execute("UPDATE tags SET uuid = ? WHERE id = ?", (t_uuid, t_row["id"]))
        tag_uuids.append(t_uuid)
        tag_titles[t_uuid] = t_row["title"]

    raw_proxy = _loads(_row_val(row, "proxy_config"))
    kek, dedupe_key = _load_local_crypto(conn)
    proxy_fp = sync_crypto.proxy_fingerprint(raw_proxy, dedupe_key) if dedupe_key else None
    enc_proxy = sync_crypto.encrypt_proxy_config(raw_proxy, kek) if kek else dict(raw_proxy)

    return {
        "uuid": _row_val(row, "uuid"),
        "name": _row_val(row, "name") or "Profile",
        "group_uuid": group_uuid,
        "group_title": group_title,
        "color": _row_val(row, "color"),
        "note": _row_val(row, "note"),
        "site_id": _row_val(row, "site_id") if _row_val(row, "site_id") is not None else 22,
        "site_url": _row_val(row, "site_url"),
        "proxy_config": enc_proxy,
        "proxy_fingerprint": proxy_fp,
        "fingerprint_config": _loads(_row_val(row, "fingerprint_config")),
        "preference_config": _loads(_row_val(row, "preference_config")),
        "tag_uuids": tag_uuids,
        "tag_titles": tag_titles,
        "seed": int(_row_val(row, "seed") or 1),
        "last_open_time": _row_val(row, "last_open_time"),
        "cookie_blob_id": _row_val(row, "cookie_blob_id"),
        "cookie_revision": int(_row_val(row, "cookie_revision") or 0),
        "bookmark_blob_id": _row_val(row, "bookmark_blob_id"),
        "bookmark_revision": int(_row_val(row, "bookmark_revision") or 0),
        "password_blob_id": _row_val(row, "password_blob_id"),
        "password_revision": int(_row_val(row, "password_revision") or 0),
        "created_at": _row_val(row, "created_at") or ts,
        "updated_at": _row_val(row, "updated_at") or ts,
        "deleted_at": _row_val(row, "deleted_at"),
        "purged_at": _row_val(row, "purged_at"),
    }


def create_group(conn, title, sort=0):
    _ensure_sync_schema(conn)
    clean_title = str(title or "").strip() or "Group"
    sort_val = int(sort or 0)
    ts = now()
    entity_uuid = _unique_entity_uuid(conn, "groups", group_uuid_for_title(clean_title))
    origin_device = get_device_id(conn)
    cur = conn.execute(
        """INSERT INTO groups
           (title, sort, created_at, uuid, revision, deleted_at, origin_device, sync_dirty)
           VALUES (?, ?, ?, ?, 0, NULL, ?, 1)""",
        (clean_title, sort_val, ts, entity_uuid, origin_device),
    )
    gid = cur.lastrowid
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
    _enqueue_outbox(conn, "group", entity_uuid, "upsert", _group_sync_payload(row), base_revision=0)
    conn.commit()
    return gid


def update_group(conn, group_id, title=None, sort=None):
    _ensure_sync_schema(conn)
    gid = int(group_id)
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
    if not row:
        return False
    if title is None and sort is None:
        return False
    new_title = row["title"] if title is None else str(title).strip()
    new_sort = int(row["sort"] or 0) if sort is None else int(sort)
    entity_uuid = _row_val(row, "uuid") or _unique_entity_uuid(
        conn, "groups", group_uuid_for_title(new_title, gid), exclude_id=gid
    )
    base_rev = int(_row_val(row, "revision") or 0)
    conn.execute(
        "UPDATE groups SET title = ?, sort = ?, uuid = ?, sync_dirty = 1 WHERE id = ?",
        (new_title, new_sort, entity_uuid, gid),
    )
    updated_row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
    _enqueue_outbox(
        conn, "group", entity_uuid, "upsert", _group_sync_payload(updated_row), base_revision=base_rev
    )
    conn.commit()
    return True


def delete_group(conn, group_id):
    _ensure_sync_schema(conn)
    gid = int(group_id)
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
    if not row:
        return 0
    entity_uuid = _row_val(row, "uuid") or group_uuid_for_title(row["title"], gid)
    base_rev = int(_row_val(row, "revision") or 0)
    payload = _group_sync_payload(row, deleted_at=now_utc())
    cur = conn.execute("DELETE FROM groups WHERE id = ?", (gid,))
    _enqueue_outbox(conn, "group", entity_uuid, "soft_delete", payload, base_revision=base_rev)
    conn.commit()
    return cur.rowcount


def create_tag(conn, title):
    _ensure_sync_schema(conn)
    clean_title = str(title if title is not None else "Tag")
    entity_uuid = _unique_entity_uuid(conn, "tags", tag_uuid_for_title(clean_title))
    origin_device = get_device_id(conn)
    cur = conn.execute(
        """INSERT INTO tags (title, uuid, revision, deleted_at, origin_device, sync_dirty)
           VALUES (?, ?, 0, NULL, ?, 1)""",
        (clean_title, entity_uuid, origin_device),
    )
    tid = cur.lastrowid
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tid,)).fetchone()
    _enqueue_outbox(conn, "tag", entity_uuid, "upsert", _tag_sync_payload(row), base_revision=0)
    conn.commit()
    return tid


def update_tag(conn, tag_id, title):
    _ensure_sync_schema(conn)
    tid = int(tag_id)
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tid,)).fetchone()
    if not row:
        conn.execute("UPDATE tags SET title = ? WHERE id = ?", (title, tid))
        conn.commit()
        return False
    entity_uuid = _row_val(row, "uuid") or _unique_entity_uuid(
        conn, "tags", tag_uuid_for_title(title or row["title"]), exclude_id=tid
    )
    base_rev = int(_row_val(row, "revision") or 0)
    conn.execute(
        "UPDATE tags SET title = ?, uuid = ?, sync_dirty = 1 WHERE id = ?",
        (title, entity_uuid, tid),
    )
    updated_row = conn.execute("SELECT * FROM tags WHERE id = ?", (tid,)).fetchone()
    _enqueue_outbox(
        conn, "tag", entity_uuid, "upsert", _tag_sync_payload(updated_row), base_revision=base_rev
    )
    conn.commit()
    return True


def delete_tag(conn, tag_id):
    _ensure_sync_schema(conn)
    tid = int(tag_id)
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tid,)).fetchone()
    if not row:
        return 0
    entity_uuid = _row_val(row, "uuid") or tag_uuid_for_title(row["title"])
    base_rev = int(_row_val(row, "revision") or 0)
    payload = _tag_sync_payload(row, deleted_at=now_utc())
    cur = conn.execute("DELETE FROM tags WHERE id = ?", (tid,))
    _enqueue_outbox(conn, "tag", entity_uuid, "soft_delete", payload, base_revision=base_rev)
    conn.commit()
    return cur.rowcount


def create_profile(conn, data):
    _ensure_sync_schema(conn)
    ts = now()
    tag_ids = _int_list(data.get("tab_id", data.get("tag_ids")))
    entity_uuid = _unique_entity_uuid(conn, "profiles", data.get("uuid") or str(uuid.uuid4()))
    origin_device = get_device_id(conn)
    proxy_config = data.get("proxy_config") or {}
    proxy_key = data.get("proxy_key") or proxy_key_for(proxy_config)
    cur = conn.execute(
        """INSERT INTO profiles
           (name, group_id, color, note, site_id, site_url,
            proxy_config, proxy_key, fingerprint_config, preference_config,
            tag_ids, seed, created_at, updated_at,
            uuid, revision, origin_device, sync_dirty)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,1)""",
        (
            data.get("name") or "Profile",
            data.get("group_id") or 1,
            data.get("color"),
            data.get("note"),
            data.get("site_id") if data.get("site_id") is not None else 22,
            data.get("site_url"),
            json.dumps(proxy_config),
            proxy_key,
            json.dumps(data.get("fingerprint_config") or {}),
            json.dumps(data.get("preference_config") or {}),
            json.dumps(tag_ids),
            int(data.get("seed") or secrets.randbelow(2**31 - 1) + 1),
            ts,
            ts,
            entity_uuid,
            origin_device,
        ),
    )
    pid = cur.lastrowid
    row = profile_get(conn, pid)
    _enqueue_outbox(
        conn, "profile", entity_uuid, "upsert", _profile_sync_payload(conn, row), base_revision=0
    )
    conn.commit()
    return pid


def update_profile(conn, profile_id, data):
    _ensure_sync_schema(conn)
    pid = int(profile_id)
    old_row = profile_get(conn, pid)
    fields, args = [], []
    for key in ("name", "group_id", "color", "note", "site_id", "site_url"):
        if key in data:
            fields.append(f"{key} = ?")
            args.append(data[key])
    for key in ("proxy_config", "fingerprint_config", "preference_config"):
        if data.get(key) is not None:
            fields.append(f"{key} = ?")
            args.append(json.dumps(data[key]))
    if data.get("proxy_config") is not None:
        fields.append("proxy_key = ?")
        args.append(data.get("proxy_key") or proxy_key_for(data["proxy_config"]))
    elif "proxy_key" in data:
        fields.append("proxy_key = ?")
        args.append(data["proxy_key"])
    tag_source = next((key for key in ("tab_id", "tag_id", "tag_ids") if key in data), None)
    if tag_source:
        fields.append("tag_ids = ?")
        args.append(json.dumps(_int_list(data[tag_source])))
    if data.get("seed"):
        fields.append("seed = ?")
        args.append(int(data["seed"]))
    if not fields:
        return
    entity_uuid = _row_val(old_row, "uuid") or _unique_entity_uuid(
        conn, "profiles", str(uuid.uuid4()), exclude_id=pid
    )
    base_rev = int(_row_val(old_row, "revision") or 0)
    fields.extend(["updated_at = ?", "uuid = ?", "sync_dirty = 1"])
    args.extend([now(), entity_uuid, pid])
    conn.execute(f"UPDATE profiles SET {', '.join(fields)} WHERE id = ?", args)
    updated_row = profile_get(conn, pid)
    if updated_row:
        payload = _profile_sync_payload(conn, updated_row)
        if data.get("seed"):
            payload["seed_reset"] = True
        _enqueue_outbox(conn, "profile", entity_uuid, "upsert", payload, base_revision=base_rev)
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
    _ensure_sync_schema(conn)
    pid = int(profile_id)
    old_row = profile_get(conn, pid)
    ts = now()
    entity_uuid = _row_val(old_row, "uuid") or _unique_entity_uuid(
        conn, "profiles", str(uuid.uuid4()), exclude_id=pid
    )
    base_rev = int(_row_val(old_row, "revision") or 0)
    conn.execute(
        "UPDATE profiles SET deleted_at = ?, updated_at = ?, uuid = ?, sync_dirty = 1 WHERE id = ?",
        (ts, ts, entity_uuid, pid),
    )
    updated_row = profile_get(conn, pid)
    if updated_row:
        _enqueue_outbox(
            conn,
            "profile",
            entity_uuid,
            "soft_delete",
            _profile_sync_payload(conn, updated_row),
            base_revision=base_rev,
        )
    conn.commit()


def restore_profile(conn, profile_id):
    _ensure_sync_schema(conn)
    pid = int(profile_id)
    old_row = profile_get(conn, pid)
    ts = now()
    entity_uuid = _row_val(old_row, "uuid") or _unique_entity_uuid(
        conn, "profiles", str(uuid.uuid4()), exclude_id=pid
    )
    base_rev = int(_row_val(old_row, "revision") or 0)
    conn.execute(
        "UPDATE profiles SET deleted_at = NULL, updated_at = ?, uuid = ?, sync_dirty = 1 WHERE id = ?",
        (ts, entity_uuid, pid),
    )
    updated_row = profile_get(conn, pid)
    if updated_row:
        _enqueue_outbox(
            conn,
            "profile",
            entity_uuid,
            "upsert",
            _profile_sync_payload(conn, updated_row),
            base_revision=base_rev,
        )
    conn.commit()


def _remove_profile_dirs(conn, profile_id):
    shutil.rmtree(launcher.PROFILES_DIR / str(profile_id), ignore_errors=True)
    local_profiles_dir = _conn_db_path(conn).parent / "profiles" / str(profile_id)
    shutil.rmtree(local_profiles_dir, ignore_errors=True)


def delete_profile_permanent(conn, profile_id):
    _ensure_sync_schema(conn)
    pid = int(profile_id)
    old_row = profile_get(conn, pid)
    if old_row:
        entity_uuid = _row_val(old_row, "uuid") or str(uuid.uuid4())
        base_rev = int(_row_val(old_row, "revision") or 0)
        ts = now_utc()
        payload = _profile_sync_payload(conn, old_row)
        payload["deleted_at"] = _row_val(old_row, "deleted_at") or ts
        payload["purged_at"] = ts
        payload["updated_at"] = ts
    else:
        entity_uuid = None
        base_rev = 0
        payload = None
    conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
    if entity_uuid and payload is not None:
        _enqueue_outbox(conn, "profile", entity_uuid, "purge", payload, base_revision=base_rev)
    conn.commit()
    _remove_profile_dirs(conn, pid)


def empty_recycle_bin(conn):
    rows = conn.execute("SELECT id FROM profiles WHERE deleted_at IS NOT NULL").fetchall()
    for row in rows:
        delete_profile_permanent(conn, row["id"])
    return len(rows)


def latest_seed(conn, profile_id):
    row = profile_get(conn, profile_id)
    return row["seed"] if row else None


def create_proxy(conn, data):
    _ensure_sync_schema(conn)
    entity_uuid = _unique_entity_uuid(conn, "proxies", data.get("uuid") or str(uuid.uuid4()))
    origin_device = get_device_id(conn)
    cur = conn.execute(
        """INSERT INTO proxies (proxy_type, proxy_ip, proxy_port, proxy_user,
           proxy_password, note, tag, uuid, revision, deleted_at, origin_device, sync_dirty)
           VALUES (?,?,?,?,?,?,?,?,0,NULL,?,1)""",
        (
            data.get("proxy_type"),
            data.get("proxy_ip"),
            data.get("proxy_port"),
            data.get("proxy_user"),
            data.get("proxy_password"),
            data.get("note"),
            data.get("tag"),
            entity_uuid,
            origin_device,
        ),
    )
    proxy_id = cur.lastrowid
    row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
    _enqueue_outbox(
        conn, "proxy", entity_uuid, "upsert", _proxy_sync_payload(conn, row), base_revision=0
    )
    conn.commit()
    return proxy_id


def update_proxy(conn, proxy_id, data):
    _ensure_sync_schema(conn)
    pid = int(proxy_id)
    row = conn.execute("SELECT * FROM proxies WHERE id = ?", (pid,)).fetchone()
    fields, args = [], []
    for key in (
        "proxy_type",
        "proxy_ip",
        "proxy_port",
        "proxy_user",
        "proxy_password",
        "note",
        "tag",
    ):
        if data.get(key) is not None:
            fields.append(f"{key} = ?")
            args.append(data[key])
    if not fields:
        return False
    if not row:
        args.append(pid)
        conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id = ?", args)
        conn.commit()
        return False
    entity_uuid = _row_val(row, "uuid") or _unique_entity_uuid(
        conn, "proxies", str(uuid.uuid4()), exclude_id=pid
    )
    base_rev = int(_row_val(row, "revision") or 0)
    fields.extend(["uuid = ?", "sync_dirty = 1"])
    args.extend([entity_uuid, pid])
    conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id = ?", args)
    updated_row = conn.execute("SELECT * FROM proxies WHERE id = ?", (pid,)).fetchone()
    _enqueue_outbox(
        conn,
        "proxy",
        entity_uuid,
        "upsert",
        _proxy_sync_payload(conn, updated_row),
        base_revision=base_rev,
    )
    conn.commit()
    return True


def delete_proxy(conn, proxy_id):
    _ensure_sync_schema(conn)
    pid = int(proxy_id)
    row = conn.execute("SELECT * FROM proxies WHERE id = ?", (pid,)).fetchone()
    if not row:
        return 0
    entity_uuid = _row_val(row, "uuid") or str(uuid.uuid4())
    base_rev = int(_row_val(row, "revision") or 0)
    payload = _proxy_sync_payload(conn, row, deleted_at=now_utc())
    cur = conn.execute("DELETE FROM proxies WHERE id = ?", (pid,))
    _enqueue_outbox(conn, "proxy", entity_uuid, "soft_delete", payload, base_revision=base_rev)
    conn.commit()
    return cur.rowcount


PROXY_CHECK_LIMIT = 500


def add_proxy_check(conn, proxy_id, ok, ip=None, latency_ms=None, error=None):
    """Catat satu hasil cek proxy dan buang baris lama di luar batas per proxy."""
    cur = conn.execute(
        """INSERT INTO proxy_checks (proxy_id, checked_at, ok, ip, latency_ms, error)
           VALUES (?,?,?,?,?,?)""",
        (
            int(proxy_id),
            now(),
            1 if ok else 0,
            ip,
            latency_ms,
            error,
        ),
    )
    conn.execute(
        """DELETE FROM proxy_checks WHERE proxy_id = ? AND id NOT IN
           (SELECT id FROM proxy_checks WHERE proxy_id = ? ORDER BY id DESC LIMIT ?)""",
        (int(proxy_id), int(proxy_id), PROXY_CHECK_LIMIT),
    )
    conn.commit()
    return cur.lastrowid


def list_proxy_checks(conn, proxy_id=None, limit=50):
    """Riwayat cek proxy, terbaru lebih dulu. Tanpa proxy_id semua baris."""
    try:
        limit = max(1, min(int(limit), PROXY_CHECK_LIMIT))
    except (TypeError, ValueError):
        limit = 50
    if proxy_id in (None, ""):
        total = conn.execute("SELECT COUNT(*) AS c FROM proxy_checks").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM proxy_checks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return total, rows
    proxy_id = int(proxy_id)
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM proxy_checks WHERE proxy_id = ?", (proxy_id,)
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM proxy_checks WHERE proxy_id = ? ORDER BY id DESC LIMIT ?",
        (proxy_id, limit),
    ).fetchall()
    return total, rows


def latest_proxy_check(conn, proxy_id):
    return conn.execute(
        "SELECT * FROM proxy_checks WHERE proxy_id = ? ORDER BY id DESC LIMIT 1",
        (int(proxy_id),),
    ).fetchone()


def clear_proxy_checks(conn, proxy_id):
    cur = conn.execute(
        "DELETE FROM proxy_checks WHERE proxy_id = ?", (int(proxy_id),)
    )
    conn.commit()
    return cur.rowcount


def list_templates(conn, page=1, limit=10):
    page = max(1, int(page))
    limit = max(1, min(int(limit), 100))
    total = conn.execute("SELECT COUNT(*) AS c FROM templates").fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM templates ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, (page - 1) * limit),
    ).fetchall()
    return total, rows


def get_template(conn, template_id):
    return conn.execute(
        "SELECT * FROM templates WHERE id = ?", (int(template_id),)
    ).fetchone()


def template_name_taken(conn, name):
    return conn.execute(
        "SELECT 1 FROM templates WHERE lower(name) = lower(?)", (name,)
    ).fetchone() is not None


def count_templates(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM templates").fetchone()["c"]


def create_template(conn, name, payload):
    _ensure_sync_schema(conn)
    ts = now()
    entity_uuid = _unique_entity_uuid(conn, "templates", str(uuid.uuid4()))
    origin_device = get_device_id(conn)
    cur = conn.execute(
        """INSERT INTO templates
           (name, payload, created_at, uuid, revision, deleted_at, origin_device, sync_dirty)
           VALUES (?,?,?,?,0,NULL,?,1)""",
        (name, json.dumps(payload), ts, entity_uuid, origin_device),
    )
    tid = cur.lastrowid
    row = get_template(conn, tid)
    _enqueue_outbox(
        conn, "template", entity_uuid, "upsert", _template_sync_payload(row), base_revision=0
    )
    conn.commit()
    return tid


def delete_template(conn, template_id):
    _ensure_sync_schema(conn)
    tid = int(template_id)
    row = get_template(conn, tid)
    if row:
        entity_uuid = _row_val(row, "uuid") or str(uuid.uuid4())
        base_rev = int(_row_val(row, "revision") or 0)
        payload = _template_sync_payload(row, deleted_at=now_utc())
    else:
        entity_uuid = None
        base_rev = 0
        payload = None
    cur = conn.execute("DELETE FROM templates WHERE id = ?", (tid,))
    if entity_uuid and payload is not None:
        _enqueue_outbox(
            conn, "template", entity_uuid, "soft_delete", payload, base_revision=base_rev
        )
    conn.commit()
    return cur.rowcount


def enqueue_dirty_entities(conn):
    """Masukkan entitas lokal yang sync_dirty = 1 namun belum ada di sync_outbox."""
    _ensure_sync_schema(conn)
    _backfill_uuids(conn)
    queued = {
        (r["entity_type"], r["entity_uuid"])
        for r in conn.execute("SELECT entity_type, entity_uuid FROM sync_outbox").fetchall()
    }
    added = 0

    for row in conn.execute("SELECT * FROM groups WHERE sync_dirty = 1 ORDER BY id").fetchall():
        is_default = row["id"] == 1 or str(row["title"] or "").strip().lower() == "default"
        if is_default and int(row["revision"] or 0) == 0:
            conn.execute("UPDATE groups SET sync_dirty = 0 WHERE id = ?", (row["id"],))
            continue
        if ("group", row["uuid"]) not in queued:
            _enqueue_outbox(
                conn,
                "group",
                row["uuid"],
                "upsert",
                _group_sync_payload(row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("group", row["uuid"]))
            added += 1

    for row in conn.execute("SELECT * FROM tags WHERE sync_dirty = 1 ORDER BY id").fetchall():
        if ("tag", row["uuid"]) not in queued:
            _enqueue_outbox(
                conn,
                "tag",
                row["uuid"],
                "upsert",
                _tag_sync_payload(row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("tag", row["uuid"]))
            added += 1

    for row in conn.execute("SELECT * FROM proxies WHERE sync_dirty = 1 ORDER BY id").fetchall():
        if ("proxy", row["uuid"]) not in queued:
            _enqueue_outbox(
                conn,
                "proxy",
                row["uuid"],
                "upsert",
                _proxy_sync_payload(conn, row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("proxy", row["uuid"]))
            added += 1

    for row in conn.execute("SELECT * FROM templates WHERE sync_dirty = 1 ORDER BY id").fetchall():
        if ("template", row["uuid"]) not in queued:
            _enqueue_outbox(
                conn,
                "template",
                row["uuid"],
                "upsert",
                _template_sync_payload(row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("template", row["uuid"]))
            added += 1

    for row in conn.execute("SELECT * FROM extensions WHERE sync_dirty = 1 ORDER BY id").fetchall():
        if ("extension", row["uuid"]) not in queued:
            op = "soft_delete" if row["deleted_at"] else "upsert"
            _enqueue_outbox(
                conn,
                "extension",
                row["uuid"],
                op,
                _extension_sync_payload(row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("extension", row["uuid"]))
            added += 1

    for row in conn.execute("SELECT * FROM profiles WHERE sync_dirty = 1 ORDER BY id").fetchall():
        if ("profile", row["uuid"]) not in queued:
            op = "soft_delete" if row["deleted_at"] else "upsert"
            _enqueue_outbox(
                conn,
                "profile",
                row["uuid"],
                op,
                _profile_sync_payload(conn, row),
                base_revision=int(row["revision"] or 0),
            )
            queued.add(("profile", row["uuid"]))
            added += 1

    if added:
        conn.commit()
    return added


def _resolve_remote_group(conn, group_uuid, group_title=None, origin_device=None):
    group_uuid = str(group_uuid or DEFAULT_GROUP_UUID).strip() or DEFAULT_GROUP_UUID
    row = conn.execute("SELECT id FROM groups WHERE uuid = ?", (group_uuid,)).fetchone()
    if row:
        return row["id"]

    if group_uuid == DEFAULT_GROUP_UUID or (
        group_title and str(group_title).strip().lower() == "default"
    ):
        def_row = conn.execute(
            "SELECT id FROM groups WHERE id = 1 OR lower(title) = 'default' ORDER BY id LIMIT 1"
        ).fetchone()
        if def_row:
            conn.execute(
                "UPDATE groups SET uuid = COALESCE(uuid, ?) WHERE id = ?",
                (DEFAULT_GROUP_UUID, def_row["id"]),
            )
            return def_row["id"]

    clean_title = str(group_title or "").strip()
    if clean_title:
        by_title = conn.execute(
            "SELECT id, uuid FROM groups WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
            (clean_title,),
        ).fetchone()
        if by_title:
            taken = conn.execute(
                "SELECT id FROM groups WHERE uuid = ? AND id <> ?",
                (group_uuid, by_title["id"]),
            ).fetchone()
            if not taken:
                conn.execute(
                    "UPDATE groups SET uuid = ?, sync_dirty = 0 WHERE id = ?",
                    (group_uuid, by_title["id"]),
                )
            return by_title["id"]

    title_to_insert = clean_title or "Group"
    cur = conn.execute(
        """INSERT INTO groups
           (title, sort, created_at, uuid, revision, deleted_at, origin_device, sync_dirty)
           VALUES (?, 0, ?, ?, 1, NULL, ?, 0)""",
        (title_to_insert, now(), group_uuid, origin_device),
    )
    return cur.lastrowid


def _resolve_remote_tags(conn, tag_uuids, tag_titles=None, origin_device=None):
    if isinstance(tag_uuids, str):
        tag_uuids = _load_list(tag_uuids)
    if not isinstance(tag_uuids, list):
        return []
    if isinstance(tag_titles, str):
        tag_titles = _loads(tag_titles)

    local_ids = []
    for idx, raw_uuid in enumerate(tag_uuids):
        t_uuid = str(raw_uuid or "").strip()
        if not t_uuid:
            continue
        row = conn.execute("SELECT id FROM tags WHERE uuid = ?", (t_uuid,)).fetchone()
        if row:
            if row["id"] not in local_ids:
                local_ids.append(row["id"])
            continue

        t_title = None
        if isinstance(tag_titles, dict):
            t_title = tag_titles.get(t_uuid)
        elif isinstance(tag_titles, list) and idx < len(tag_titles):
            t_title = tag_titles[idx]

        clean_title = str(t_title or "").strip()
        if clean_title:
            by_title = conn.execute(
                "SELECT id FROM tags WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
                (clean_title,),
            ).fetchone()
            if by_title:
                taken = conn.execute(
                    "SELECT id FROM tags WHERE uuid = ? AND id <> ?",
                    (t_uuid, by_title["id"]),
                ).fetchone()
                if not taken:
                    conn.execute(
                        "UPDATE tags SET uuid = ?, sync_dirty = 0 WHERE id = ?",
                        (t_uuid, by_title["id"]),
                    )
                if by_title["id"] not in local_ids:
                    local_ids.append(by_title["id"])
                continue

        cur = conn.execute(
            """INSERT INTO tags (title, uuid, revision, deleted_at, origin_device, sync_dirty)
               VALUES (?, ?, 1, NULL, ?, 0)""",
            (clean_title or "Tag", t_uuid, origin_device),
        )
        local_ids.append(cur.lastrowid)

    return local_ids


def apply_remote_change(conn, change):
    """Terapkan satu entri change dari POST /v1/sync/pull ke DB lokal dengan sync_dirty = 0."""
    _ensure_sync_schema(conn)
    if not isinstance(change, dict):
        return False

    entity_type = str(change.get("entity_type") or "").strip()
    entity_uuid = str(change.get("entity_uuid") or "").strip()
    operation = str(change.get("operation") or "upsert").strip()
    revision = int(change.get("revision") or 1)
    origin_device = change.get("origin_device")
    changed_at = change.get("changed_at") or now()
    raw_payload = change.get("payload")
    payload = _loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload or {})

    if not entity_type or not entity_uuid:
        return False

    # Jangan timpa perubahan lokal yang masih antre di outbox kecuali operasi purge
    if operation != "purge":
        pending = conn.execute(
            "SELECT 1 FROM sync_outbox WHERE entity_type = ? AND entity_uuid = ? LIMIT 1",
            (entity_type, entity_uuid),
        ).fetchone()
        if pending:
            return False

    kek, _ = _load_local_crypto(conn)

    if entity_type == "group":
        deleted_at = payload.get("deleted_at")
        if operation in ("soft_delete", "purge") or deleted_at:
            row = conn.execute(
                "SELECT id, title FROM groups WHERE uuid = ?", (entity_uuid,)
            ).fetchone()
            if row and row["id"] != 1 and str(row["title"] or "").strip().lower() != "default":
                conn.execute("UPDATE profiles SET group_id = 1 WHERE group_id = ?", (row["id"],))
                conn.execute("DELETE FROM groups WHERE id = ?", (row["id"],))
            conn.commit()
            return True

        title = str(payload.get("title") or "Group").strip() or "Group"
        sort_val = int(payload.get("sort") or 0)
        created_at = payload.get("created_at") or changed_at
        row = conn.execute("SELECT * FROM groups WHERE uuid = ?", (entity_uuid,)).fetchone()
        if not row:
            if entity_uuid == DEFAULT_GROUP_UUID or title.lower() == "default":
                row = conn.execute(
                    "SELECT * FROM groups WHERE id = 1 OR lower(title) = 'default' ORDER BY id LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM groups WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
                    (title,),
                ).fetchone()
        if row:
            conn.execute(
                """UPDATE groups
                   SET title = ?, sort = ?, uuid = ?, revision = ?,
                       deleted_at = NULL, origin_device = ?, sync_dirty = 0
                   WHERE id = ?""",
                (title, sort_val, entity_uuid, revision, origin_device, row["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO groups
                   (title, sort, created_at, uuid, revision, deleted_at, origin_device, sync_dirty)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, 0)""",
                (title, sort_val, created_at, entity_uuid, revision, origin_device),
            )
        conn.commit()
        return True

    if entity_type == "tag":
        deleted_at = payload.get("deleted_at")
        if operation in ("soft_delete", "purge") or deleted_at:
            row = conn.execute("SELECT id FROM tags WHERE uuid = ?", (entity_uuid,)).fetchone()
            if row:
                conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))
            conn.commit()
            return True

        title = str(payload.get("title") or "Tag")
        row = conn.execute("SELECT * FROM tags WHERE uuid = ?", (entity_uuid,)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM tags WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
                (title,),
            ).fetchone()
        if row:
            conn.execute(
                """UPDATE tags
                   SET title = ?, uuid = ?, revision = ?,
                       deleted_at = NULL, origin_device = ?, sync_dirty = 0
                   WHERE id = ?""",
                (title, entity_uuid, revision, origin_device, row["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO tags
                   (title, uuid, revision, deleted_at, origin_device, sync_dirty)
                   VALUES (?, ?, ?, NULL, ?, 0)""",
                (title, entity_uuid, revision, origin_device),
            )
        conn.commit()
        return True

    if entity_type == "proxy":
        deleted_at = payload.get("deleted_at")
        if operation in ("soft_delete", "purge") or deleted_at:
            row = conn.execute("SELECT id FROM proxies WHERE uuid = ?", (entity_uuid,)).fetchone()
            if row:
                conn.execute("DELETE FROM proxies WHERE id = ?", (row["id"],))
            conn.commit()
            return True

        dec_proxy = sync_crypto.decrypt_proxy_config(payload, kek)
        proxy_password = dec_proxy.get("proxy_password")
        row = conn.execute("SELECT * FROM proxies WHERE uuid = ?", (entity_uuid,)).fetchone()
        if row:
            conn.execute(
                """UPDATE proxies
                   SET proxy_type = ?, proxy_ip = ?, proxy_port = ?, proxy_user = ?,
                       proxy_password = COALESCE(?, proxy_password),
                       note = ?, tag = ?, revision = ?, deleted_at = NULL,
                       origin_device = ?, sync_dirty = 0
                   WHERE id = ?""",
                (
                    payload.get("proxy_type"),
                    payload.get("proxy_ip"),
                    payload.get("proxy_port"),
                    payload.get("proxy_user"),
                    proxy_password,
                    payload.get("note"),
                    payload.get("tag"),
                    revision,
                    origin_device,
                    row["id"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO proxies
                   (proxy_type, proxy_ip, proxy_port, proxy_user, proxy_password,
                    note, tag, uuid, revision, deleted_at, origin_device, sync_dirty)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL,?,0)""",
                (
                    payload.get("proxy_type"),
                    payload.get("proxy_ip"),
                    payload.get("proxy_port"),
                    payload.get("proxy_user"),
                    proxy_password,
                    payload.get("note"),
                    payload.get("tag"),
                    entity_uuid,
                    revision,
                    origin_device,
                ),
            )
        conn.commit()
        return True

    if entity_type == "template":
        deleted_at = payload.get("deleted_at")
        if operation in ("soft_delete", "purge") or deleted_at:
            row = conn.execute(
                "SELECT id FROM templates WHERE uuid = ?", (entity_uuid,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM templates WHERE id = ?", (row["id"],))
            conn.commit()
            return True

        name = str(payload.get("name") or "Template")
        tpl_payload = payload.get("payload")
        tpl_json = (
            tpl_payload
            if isinstance(tpl_payload, str)
            else json.dumps(tpl_payload or {}, ensure_ascii=False)
        )
        created_at = payload.get("created_at") or changed_at
        row = conn.execute("SELECT * FROM templates WHERE uuid = ?", (entity_uuid,)).fetchone()
        if row:
            conn.execute(
                """UPDATE templates
                   SET name = ?, payload = ?, revision = ?, deleted_at = NULL,
                       origin_device = ?, sync_dirty = 0
                   WHERE id = ?""",
                (name, tpl_json, revision, origin_device, row["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO templates
                   (name, payload, created_at, uuid, revision, deleted_at, origin_device, sync_dirty)
                   VALUES (?,?,?,?,?,NULL,?,0)""",
                (name, tpl_json, created_at, entity_uuid, revision, origin_device),
            )
        conn.commit()
        return True

    if entity_type == "extension":
        deleted_at = payload.get("deleted_at")
        if operation in ("soft_delete", "purge") or deleted_at:
            row = conn.execute(
                "SELECT id FROM extensions WHERE uuid = ?", (entity_uuid,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM extensions WHERE id = ?", (row["id"],))
            conn.commit()
            return True

        slug = str(payload.get("slug") or entity_uuid)
        title = payload.get("title")
        version = payload.get("version")
        archive_blob_id = payload.get("archive_blob_id")
        archive_sha256 = payload.get("archive_sha256")
        created_at = payload.get("created_at") or changed_at
        row = conn.execute(
            "SELECT * FROM extensions WHERE uuid = ? OR slug = ? ORDER BY id LIMIT 1",
            (entity_uuid, slug),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE extensions
                   SET slug = ?, title = ?, version = ?, uuid = ?, revision = ?,
                       archive_blob_id = COALESCE(?, archive_blob_id),
                       archive_sha256 = COALESCE(?, archive_sha256),
                       deleted_at = NULL, origin_device = ?, sync_dirty = 0
                   WHERE id = ?""",
                (
                    slug,
                    title,
                    version,
                    entity_uuid,
                    revision,
                    archive_blob_id,
                    archive_sha256,
                    origin_device,
                    row["id"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO extensions
                   (slug, title, version, path, created_at, uuid, revision,
                    archive_blob_id, archive_sha256, deleted_at, origin_device, sync_dirty)
                   VALUES (?,?,?,NULL,?,?,?,?,?,NULL,?,0)""",
                (
                    slug,
                    title,
                    version,
                    created_at,
                    entity_uuid,
                    revision,
                    archive_blob_id,
                    archive_sha256,
                    origin_device,
                ),
            )
        conn.commit()

        if archive_blob_id:
            from . import extensions, sync_agent

            ext_dir = extensions._extensions_dir(conn) / slug
            if not ext_dir.is_dir() or not (ext_dir / "manifest.json").is_file():
                try:
                    sync_agent.download_and_install_extension(
                        conn,
                        slug,
                        archive_blob_id,
                        extension_uuid=entity_uuid,
                        title=title,
                        version=version,
                    )
                except Exception:
                    pass
        return True

    if entity_type == "profile":
        purged_at = payload.get("purged_at")
        if operation == "purge" or purged_at is not None:
            row = conn.execute(
                "SELECT id FROM profiles WHERE uuid = ?", (entity_uuid,)
            ).fetchone()
            if row:
                local_id = row["id"]
                conn.execute("DELETE FROM profiles WHERE id = ?", (local_id,))
                conn.commit()
                _remove_profile_dirs(conn, local_id)
            else:
                conn.commit()
            return True

        group_id = _resolve_remote_group(
            conn,
            payload.get("group_uuid"),
            group_title=payload.get("group_title"),
            origin_device=origin_device,
        )
        local_tag_ids = _resolve_remote_tags(
            conn,
            payload.get("tag_uuids") or [],
            tag_titles=payload.get("tag_titles"),
            origin_device=origin_device,
        )

        raw_proxy = payload.get("proxy_config") or {}
        if isinstance(raw_proxy, str):
            raw_proxy = _loads(raw_proxy)
        proxy_config = sync_crypto.decrypt_proxy_config(raw_proxy, kek)
        proxy_key = proxy_key_for(proxy_config)

        fp_config = payload.get("fingerprint_config") or {}
        if isinstance(fp_config, str):
            fp_config = _loads(fp_config)
        pref_config = payload.get("preference_config") or {}
        if isinstance(pref_config, str):
            pref_config = _loads(pref_config)

        deleted_at = payload.get("deleted_at")
        if operation == "soft_delete" and not deleted_at:
            deleted_at = changed_at

        created_at = payload.get("created_at") or changed_at
        updated_at = payload.get("updated_at") or changed_at
        seed_val = int(payload.get("seed") or secrets.randbelow(2**31 - 1) + 1)
        cookie_blob_id = payload.get("cookie_blob_id") or payload.get("latest_cookie_blob_id")
        cookie_revision = int(payload.get("cookie_revision") or payload.get("latest_cookie_revision") or 0)
        bookmark_blob_id = payload.get("bookmark_blob_id") or payload.get("latest_bookmark_blob_id")
        bookmark_revision = int(payload.get("bookmark_revision") or payload.get("latest_bookmark_revision") or 0)
        password_blob_id = payload.get("password_blob_id") or payload.get("latest_password_blob_id")
        password_revision = int(payload.get("password_revision") or payload.get("latest_password_revision") or 0)
        is_self_origin = bool(origin_device and origin_device == get_device_id(conn))

        existing = conn.execute(
            "SELECT * FROM profiles WHERE uuid = ?", (entity_uuid,)
        ).fetchone()
        if existing:
            local_cookie_blob = (
                cookie_blob_id
                if is_self_origin and cookie_blob_id
                else existing["cookie_blob_id"]
            )
            local_cookie_rev = (
                max(cookie_revision, int(existing["cookie_revision"] or 0))
                if is_self_origin
                else int(existing["cookie_revision"] or 0)
            )
            local_bm_blob = bookmark_blob_id or _row_val(existing, "bookmark_blob_id")
            local_bm_rev = (
                max(bookmark_revision, int(_row_val(existing, "bookmark_revision") or 0))
                if is_self_origin
                else int(_row_val(existing, "bookmark_revision") or 0)
            )
            local_pw_blob = password_blob_id or _row_val(existing, "password_blob_id")
            local_pw_rev = (
                max(password_revision, int(_row_val(existing, "password_revision") or 0))
                if is_self_origin
                else int(_row_val(existing, "password_revision") or 0)
            )
            conn.execute(
                """UPDATE profiles SET
                       name = ?,
                       group_id = ?,
                       color = ?,
                       note = ?,
                       site_id = ?,
                       site_url = ?,
                       proxy_config = ?,
                       proxy_key = ?,
                       fingerprint_config = ?,
                       preference_config = ?,
                       tag_ids = ?,
                       last_open_time = ?,
                       seed = ?,
                       created_at = ?,
                       updated_at = ?,
                       deleted_at = ?,
                       purged_at = NULL,
                       revision = ?,
                       origin_device = ?,
                       cookie_blob_id = ?,
                       cookie_revision = ?,
                       bookmark_blob_id = ?,
                       bookmark_revision = ?,
                       password_blob_id = ?,
                       password_revision = ?,
                       sync_dirty = 0
                   WHERE id = ?""",
                (
                    payload.get("name") or existing["name"],
                    group_id,
                    payload.get("color"),
                    payload.get("note"),
                    payload.get("site_id")
                    if payload.get("site_id") is not None
                    else existing["site_id"],
                    payload.get("site_url"),
                    json.dumps(proxy_config),
                    proxy_key,
                    json.dumps(fp_config),
                    json.dumps(pref_config),
                    json.dumps(local_tag_ids),
                    payload.get("last_open_time")
                    if payload.get("last_open_time") is not None
                    else existing["last_open_time"],
                    seed_val,
                    existing["created_at"] or created_at,
                    updated_at,
                    deleted_at,
                    revision,
                    origin_device,
                    local_cookie_blob,
                    local_cookie_rev,
                    local_bm_blob,
                    local_bm_rev,
                    local_pw_blob,
                    local_pw_rev,
                    existing["id"],
                ),
            )
        else:
            init_cookie_blob = cookie_blob_id if is_self_origin else None
            init_cookie_rev = cookie_revision if is_self_origin else 0
            init_bm_blob = bookmark_blob_id
            init_bm_rev = bookmark_revision if is_self_origin else 0
            init_pw_blob = password_blob_id
            init_pw_rev = password_revision if is_self_origin else 0
            conn.execute(
                """INSERT INTO profiles
                   (name, group_id, color, note, site_id, site_url,
                    proxy_config, proxy_key, fingerprint_config, preference_config,
                    tag_ids, last_open_time, seed, created_at, updated_at, deleted_at,
                    uuid, revision, origin_device, purged_at,
                    cookie_blob_id, cookie_revision,
                    bookmark_blob_id, bookmark_revision,
                    password_blob_id, password_revision,
                    sync_dirty)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,0)""",
                (
                    payload.get("name") or "Profile",
                    group_id,
                    payload.get("color"),
                    payload.get("note"),
                    payload.get("site_id") if payload.get("site_id") is not None else 22,
                    payload.get("site_url"),
                    json.dumps(proxy_config),
                    proxy_key,
                    json.dumps(fp_config),
                    json.dumps(pref_config),
                    json.dumps(local_tag_ids),
                    payload.get("last_open_time"),
                    seed_val,
                    created_at,
                    updated_at,
                    deleted_at,
                    entity_uuid,
                    revision,
                    origin_device,
                    init_cookie_blob,
                    init_cookie_rev,
                    init_bm_blob,
                    init_bm_rev,
                    init_pw_blob,
                    init_pw_rev,
                ),
            )
        conn.commit()
        return True

    if entity_type == "cookie_blob":
        if origin_device and origin_device == get_device_id(conn):
            row = conn.execute(
                "SELECT id, cookie_revision FROM profiles WHERE uuid = ?",
                (entity_uuid,),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE profiles
                       SET cookie_blob_id = COALESCE(?, cookie_blob_id),
                           cookie_revision = MAX(?, COALESCE(cookie_revision, 0)),
                           cookie_sha256 = COALESCE(?, cookie_sha256)
                       WHERE id = ?""",
                    (
                        payload.get("blob_id"),
                        int(payload.get("cookie_revision") or revision or 0),
                        payload.get("sha256_plain"),
                        row["id"],
                    ),
                )
                conn.commit()
        return True

    if entity_type == "bookmark_blob":
        row = conn.execute(
            "SELECT id, bookmark_revision FROM profiles WHERE uuid = ?",
            (entity_uuid,),
        ).fetchone()
        if row:
            if origin_device and origin_device == get_device_id(conn):
                conn.execute(
                    """UPDATE profiles
                       SET bookmark_blob_id = COALESCE(?, bookmark_blob_id),
                           bookmark_revision = MAX(?, COALESCE(bookmark_revision, 0)),
                           bookmark_sha256 = COALESCE(?, bookmark_sha256)
                       WHERE id = ?""",
                    (
                        payload.get("blob_id") or payload.get("bookmark_blob_id"),
                        int(payload.get("bookmark_revision") or revision or 0),
                        payload.get("sha256_plain"),
                        row["id"],
                    ),
                )
            else:
                conn.execute(
                    """UPDATE profiles
                       SET bookmark_blob_id = COALESCE(?, bookmark_blob_id)
                       WHERE id = ?""",
                    (
                        payload.get("blob_id") or payload.get("bookmark_blob_id"),
                        row["id"],
                    ),
                )
            conn.commit()
        return True

    if entity_type == "password_blob":
        row = conn.execute(
            "SELECT id, password_revision FROM profiles WHERE uuid = ?",
            (entity_uuid,),
        ).fetchone()
        if row:
            if origin_device and origin_device == get_device_id(conn):
                conn.execute(
                    """UPDATE profiles
                       SET password_blob_id = COALESCE(?, password_blob_id),
                           password_revision = MAX(?, COALESCE(password_revision, 0)),
                           password_sha256 = COALESCE(?, password_sha256)
                       WHERE id = ?""",
                    (
                        payload.get("blob_id") or payload.get("password_blob_id"),
                        int(payload.get("password_revision") or revision or 0),
                        payload.get("sha256_plain"),
                        row["id"],
                    ),
                )
            else:
                conn.execute(
                    """UPDATE profiles
                       SET password_blob_id = COALESCE(?, password_blob_id)
                       WHERE id = ?""",
                    (
                        payload.get("blob_id") or payload.get("password_blob_id"),
                        row["id"],
                    ),
                )
            conn.commit()
        return True

    return False


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
