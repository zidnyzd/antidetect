"""Server sinkronisasi metadata untuk antidetect."""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import sync_crypto
from .paths import DATA_DIR

DEFAULT_GROUP_UUID = "00000000-0000-4000-8000-000000000001"
MAX_COOKIE_BLOB_BYTES = 10 * 1024 * 1024
BLOB_RETENTION_COUNT = 3

SERVER_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    app_version TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_token_hash ON devices (token_hash);

CREATE TABLE IF NOT EXISTS enrollment_tokens (
    token_hash TEXT PRIMARY KEY,
    label TEXT,
    expires_at INTEGER NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS server_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_groups (
    uuid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_sync_groups_title ON sync_groups (lower(title));

CREATE TABLE IF NOT EXISTS sync_tags (
    uuid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS sync_proxies (
    uuid TEXT PRIMARY KEY,
    proxy_type TEXT,
    proxy_ip TEXT,
    proxy_port INTEGER,
    proxy_user TEXT,
    proxy_password_enc TEXT,
    proxy_fingerprint TEXT,
    note TEXT,
    tag TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_sync_proxies_fingerprint ON sync_proxies (proxy_fingerprint);

CREATE TABLE IF NOT EXISTS sync_templates (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    payload TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS sync_extensions (
    uuid TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT,
    version TEXT,
    archive_blob_id TEXT,
    archive_sha256 TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS sync_profiles (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    group_uuid TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001',
    color TEXT,
    note TEXT,
    site_id INTEGER,
    site_url TEXT,
    proxy_config TEXT NOT NULL DEFAULT '{}',
    proxy_fingerprint TEXT,
    fingerprint_config TEXT NOT NULL DEFAULT '{}',
    preference_config TEXT NOT NULL DEFAULT '{}',
    tag_uuids TEXT NOT NULL DEFAULT '[]',
    seed INTEGER NOT NULL,
    last_open_time INTEGER,
    cookie_blob_id TEXT,
    cookie_revision INTEGER NOT NULL DEFAULT 0,
    cookie_updated_at TEXT,
    cookie_origin_device TEXT,
    last_fencing_token INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    purged_at TEXT,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_sync_profiles_group ON sync_profiles (group_uuid);
CREATE INDEX IF NOT EXISTS idx_sync_profiles_deleted ON sync_profiles (deleted_at, purged_at);

CREATE TABLE IF NOT EXISTS profile_blobs (
    blob_id TEXT PRIMARY KEY,
    profile_uuid TEXT NOT NULL REFERENCES sync_profiles(uuid),
    blob_kind TEXT NOT NULL CHECK (blob_kind IN ('cookies', 'bookmarks', 'extension_pkg', 'snapshot')),
    revision INTEGER NOT NULL,
    sha256_plain TEXT NOT NULL,
    sha256_cipher TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    encryption_scheme TEXT NOT NULL DEFAULT 'aes-256-gcm-v1',
    storage_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    origin_device TEXT NOT NULL REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_profile_blobs_profile ON profile_blobs (profile_uuid, blob_kind, revision DESC);

CREATE TABLE IF NOT EXISTS profile_leases (
    profile_uuid TEXT PRIMARY KEY REFERENCES sync_profiles(uuid),
    holder_device_id TEXT NOT NULL REFERENCES devices(device_id),
    lease_token TEXT NOT NULL UNIQUE,
    fencing_token INTEGER NOT NULL,
    acquired_at INTEGER NOT NULL,
    renewed_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_leases_expires ON profile_leases (expires_at);

CREATE TABLE IF NOT EXISTS change_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN ('profile', 'group', 'tag', 'proxy', 'template', 'extension', 'cookie_blob')
    ),
    entity_uuid TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'soft_delete', 'purge')),
    revision INTEGER NOT NULL,
    origin_device TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_entity ON change_log (entity_type, entity_uuid, seq);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_uuid TEXT NOT NULL,
    base_revision INTEGER NOT NULL,
    server_revision INTEGER NOT NULL,
    losing_device TEXT NOT NULL,
    winning_device TEXT NOT NULL,
    losing_payload TEXT NOT NULL,
    winning_payload TEXT NOT NULL,
    reason TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by_device TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conflicts_unresolved ON conflicts (entity_uuid, resolved_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT,
    action TEXT NOT NULL,
    target_uuid TEXT,
    ip_address TEXT,
    status_code INTEGER NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs (created_at);

CREATE TABLE IF NOT EXISTS processed_mutations (
    idempotency_key TEXT PRIMARY KEY,
    entity_uuid TEXT NOT NULL,
    status TEXT NOT NULL,
    new_revision INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    conflict_id TEXT,
    merged_payload TEXT,
    created_at TEXT NOT NULL
);
"""


class SyncServerError(Exception):
    def __init__(self, code, message, http_status=400, data=None):
        if isinstance(code, int) and isinstance(message, int):
            actual_http = code
            actual_code = message
            actual_msg = http_status if isinstance(http_status, str) else str(http_status)
            actual_data = data
        else:
            actual_code = code
            actual_msg = message
            actual_http = http_status
            actual_data = data
        super().__init__(actual_msg)
        self.code = actual_code
        self.message = actual_msg
        self.http_status = actual_http
        self.data = actual_data


class EnrollmentToken(str):
    def __new__(cls, token, label=None, expires_at=0):
        obj = super().__new__(cls, token)
        obj.token = token
        obj.label = label
        obj.expires_at = expires_at
        return obj

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return super().__getitem__(key)
        if key == "token":
            return self.token
        if key == "label":
            return self.label
        if key == "expires_at":
            return self.expires_at
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def resolve_db_path(db_path=None):
    if db_path is None:
        return DATA_DIR / "server_sync.db"
    candidate = Path(db_path)
    if candidate.is_dir() or str(db_path).endswith("/"):
        return candidate / "server_sync.db"
    if candidate.suffix != ".db" and not candidate.exists():
        # Jika diberikan path direktori yang belum dibuat
        if "server_sync" not in candidate.name and not candidate.suffix:
            return candidate / "server_sync.db"
    return candidate


def _server_db_path(conn):
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        for row in rows:
            name = row[1] if isinstance(row, tuple) else row["name"]
            file_path = row[2] if isinstance(row, tuple) else row["file"]
            if name == "main" and file_path:
                return Path(file_path)
    except Exception:
        pass
    return resolve_db_path()


class LocalFilesystemBlobStore:
    def __init__(self, target=None):
        if target is None:
            db_file = resolve_db_path()
            self.root_dir = db_file.parent / "blobs"
        else:
            candidate = Path(target)
            if candidate.name == "blobs":
                self.root_dir = candidate
            elif candidate.suffix == ".db":
                self.root_dir = candidate.parent / "blobs"
            else:
                db_file = resolve_db_path(candidate)
                self.root_dir = db_file.parent / "blobs"

    @staticmethod
    def _prefix(blob_id):
        clean = str(blob_id or "").strip()
        if clean.startswith("blob_") and len(clean) >= 7:
            clean = clean[5:]
        return (clean[:2] or "00").lower()

    def storage_key(self, blob_id):
        clean_id = Path(str(blob_id or "").strip()).name
        if not clean_id:
            raise SyncServerError(400, 2003, "blob_id tidak valid")
        prefix_2 = self._prefix(clean_id)
        return f"{prefix_2}/{clean_id}.bin"

    def blob_path(self, blob_id):
        clean_id = Path(str(blob_id or "").strip()).name
        if not clean_id:
            raise SyncServerError(400, 2003, "blob_id tidak valid")
        prefix_2 = self._prefix(clean_id)
        return self.root_dir / prefix_2 / f"{clean_id}.bin"

    def exists(self, blob_id):
        try:
            return self.blob_path(blob_id).is_file()
        except Exception:
            return False

    def put(self, blob_id, data):
        path = self.blob_path(blob_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            raw_bytes = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            raw_bytes = bytes(data)
        else:
            raise SyncServerError(400, 2003, "Data blob tidak valid")
        tmp_path = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(raw_bytes)
                handle.flush()
            os.replace(str(tmp_path), str(path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return self.storage_key(blob_id)

    def get(self, blob_id):
        path = self.blob_path(blob_id)
        if not path.is_file():
            raise SyncServerError(404, 2008, "Blob tidak ditemukan")
        try:
            return path.read_bytes()
        except OSError as error:
            raise SyncServerError(404, 2008, f"Gagal membaca blob: {error}") from error

    def delete(self, blob_id):
        try:
            path = self.blob_path(blob_id)
            if path.exists():
                path.unlink()
                return True
        except OSError:
            pass
        return False


def connect_server_db(db_path=None):
    target = resolve_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_server_db(db_path=None):
    conn = connect_server_db(db_path)
    try:
        conn.executescript(SERVER_SCHEMA)
        row = conn.execute(
            "SELECT value FROM server_meta WHERE key = 'kdf_salt_hex'"
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO server_meta (key, value) VALUES ('kdf_salt_hex', ?)",
                (sync_crypto.generate_salt(),),
            )
        conn.commit()
    finally:
        conn.close()


def _get_meta(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM server_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def _set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO server_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _audit(conn, device_id, action, status_code, target_uuid=None, ip_address=None, detail=None):
    conn.execute(
        """INSERT INTO audit_logs
           (device_id, action, target_uuid, ip_address, status_code, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (device_id, action, target_uuid, ip_address, int(status_code), detail, now_utc()),
    )


def create_enrollment_token(db_path=None, label=None, ttl_minutes=60):
    init_server_db(db_path)
    token = f"ad_enroll_{secrets.token_hex(16)}"
    token_hash = _hash_token(token)
    expires_at = int(time.time()) + int(ttl_minutes or 60) * 60
    conn = connect_server_db(db_path)
    try:
        conn.execute(
            """INSERT INTO enrollment_tokens
               (token_hash, label, expires_at, used_at, created_at)
               VALUES (?, ?, ?, NULL, ?)""",
            (token_hash, label, expires_at, now_utc()),
        )
        _audit(conn, None, "token-create", 200, detail=label)
        conn.commit()
    finally:
        conn.close()
    return EnrollmentToken(token, label=label, expires_at=expires_at)


def _loads_json(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default


def _dumps_json(value, default="{}"):
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row_to_payload(entity_type, row):
    if row is None:
        return {}
    if entity_type == "group":
        return {
            "uuid": row["uuid"],
            "title": row["title"],
            "sort": row["sort"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }
    if entity_type == "tag":
        return {
            "uuid": row["uuid"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }
    if entity_type == "proxy":
        return {
            "uuid": row["uuid"],
            "proxy_type": row["proxy_type"],
            "proxy_ip": row["proxy_ip"],
            "proxy_port": row["proxy_port"],
            "proxy_user": row["proxy_user"],
            "proxy_password_enc": row["proxy_password_enc"],
            "proxy_fingerprint": row["proxy_fingerprint"],
            "note": row["note"],
            "tag": row["tag"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }
    if entity_type == "template":
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "payload": _loads_json(row["payload"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }
    if entity_type == "extension":
        return {
            "uuid": row["uuid"],
            "slug": row["slug"],
            "title": row["title"],
            "version": row["version"],
            "archive_blob_id": row["archive_blob_id"],
            "archive_sha256": row["archive_sha256"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }
    if entity_type == "profile":
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "group_uuid": row["group_uuid"],
            "color": row["color"],
            "note": row["note"],
            "site_id": row["site_id"],
            "site_url": row["site_url"],
            "proxy_config": _loads_json(row["proxy_config"], {}),
            "proxy_fingerprint": row["proxy_fingerprint"],
            "fingerprint_config": _loads_json(row["fingerprint_config"], {}),
            "preference_config": _loads_json(row["preference_config"], {}),
            "tag_uuids": _loads_json(row["tag_uuids"], []),
            "seed": row["seed"],
            "last_open_time": row["last_open_time"],
            "cookie_blob_id": row["cookie_blob_id"],
            "cookie_revision": row["cookie_revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "purged_at": row["purged_at"],
        }
    return dict(row)


def _merge_conflict_payload(
    entity_type,
    base_payload,
    server_payload,
    incoming_payload,
    server_updated_at,
    server_device,
    client_updated_at,
    client_device,
):
    """Gabungkan perubahan per-field dengan aturan LWW sesuai Bagian 7 SYNC-PLAN."""
    incoming_wins = (str(client_updated_at or ""), str(client_device or "")) >= (
        str(server_updated_at or ""),
        str(server_device or ""),
    )
    merged = dict(server_payload)
    all_keys = set(server_payload.keys()) | set(incoming_payload.keys())
    atomic_proxy_handled = False

    for key in all_keys:
        if key in ("uuid", "created_at", "purged_at"):
            continue
        if key == "last_open_time":
            s_val = server_payload.get("last_open_time")
            i_val = incoming_payload.get("last_open_time")
            if s_val is not None and i_val is not None:
                merged["last_open_time"] = max(int(s_val), int(i_val))
            elif i_val is not None:
                merged["last_open_time"] = int(i_val)
            continue
        if key == "seed":
            if incoming_payload.get("seed_reset"):
                merged["seed"] = incoming_payload.get("seed")
            else:
                merged["seed"] = server_payload.get("seed") or incoming_payload.get("seed")
            continue
        if key in ("proxy_config", "proxy_fingerprint"):
            if atomic_proxy_handled:
                continue
            atomic_proxy_handled = True
            s_proxy = server_payload.get("proxy_config")
            i_proxy = incoming_payload.get("proxy_config")
            b_proxy = base_payload.get("proxy_config") if base_payload else None
            s_changed = b_proxy is None or s_proxy != b_proxy
            i_changed = b_proxy is None or i_proxy != b_proxy
            if i_changed and not s_changed:
                pick_incoming = True
            elif s_changed and not i_changed:
                pick_incoming = False
            else:
                pick_incoming = incoming_wins
            if pick_incoming and i_proxy is not None:
                merged["proxy_config"] = i_proxy
                merged["proxy_fingerprint"] = incoming_payload.get("proxy_fingerprint")
            continue

        s_val = server_payload.get(key)
        i_val = incoming_payload.get(key)
        if s_val == i_val:
            continue
        if base_payload:
            b_val = base_payload.get(key)
            s_changed = s_val != b_val
            i_changed = i_val != b_val
            if i_changed and not s_changed:
                merged[key] = i_val
            elif s_changed and not i_changed:
                merged[key] = s_val
            elif incoming_wins:
                merged[key] = i_val
        else:
            if incoming_wins and key in incoming_payload:
                merged[key] = i_val

    merged["updated_at"] = max(str(server_updated_at or ""), str(client_updated_at or "")) or now_utc()
    return merged, incoming_wins


def handle_register_device(conn, body, ip_address=None):
    enrollment_token = str(body.get("enrollment_token") or "").strip()
    if not enrollment_token:
        raise SyncServerError(2003, "enrollment_token wajib diisi", 400)
    device_id = str(body.get("device_id") or "").strip() or str(secrets.token_hex(16))
    device_name = str(body.get("device_name") or "Device").strip()
    platform = str(body.get("platform") or "linux").strip()
    app_version = str(body.get("app_version") or "0.1.0").strip()

    now_epoch = int(time.time())
    ts = now_utc()
    enroll_hash = _hash_token(enrollment_token)

    conn.execute("BEGIN IMMEDIATE")
    token_row = conn.execute(
        "SELECT * FROM enrollment_tokens WHERE token_hash = ?", (enroll_hash,)
    ).fetchone()
    if not token_row:
        _audit(conn, device_id, "device-register", 401, detail="invalid_enrollment_token", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Enrollment token tidak valid", 401)
    if token_row["expires_at"] <= now_epoch:
        _audit(conn, device_id, "device-register", 401, detail="expired_enrollment_token", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Enrollment token sudah kedaluwarsa", 401)
    if token_row["used_at"] is not None:
        _audit(conn, device_id, "device-register", 401, detail="used_enrollment_token", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Enrollment token sudah pernah digunakan", 401)

    existing_salt = _get_meta(conn, "kdf_salt_hex")
    existing_check = _get_meta(conn, "key_check_value")

    req_salt = body.get("kdf_salt_hex")
    req_check = body.get("key_check_value")
    req_passphrase = body.get("passphrase")

    if not existing_check:
        if req_salt and req_check:
            existing_salt = str(req_salt)
            existing_check = str(req_check)
            _set_meta(conn, "kdf_salt_hex", existing_salt)
            _set_meta(conn, "key_check_value", existing_check)
        elif req_passphrase:
            if not existing_salt:
                existing_salt = sync_crypto.generate_salt()
                _set_meta(conn, "kdf_salt_hex", existing_salt)
            kek = sync_crypto.derive_kek(req_passphrase, existing_salt)
            existing_check = sync_crypto.compute_key_check(kek)
            _set_meta(conn, "key_check_value", existing_check)
        elif req_check:
            existing_check = str(req_check)
            _set_meta(conn, "key_check_value", existing_check)
    else:
        if req_passphrase and not sync_crypto.verify_passphrase(
            req_passphrase, existing_salt, existing_check
        ):
            _audit(conn, device_id, "device-register", 401, detail="passphrase_mismatch", ip_address=ip_address)
            conn.commit()
            raise SyncServerError(2001, "Frasa sandi sinkronisasi tidak cocok", 401)

    device_token = f"ad_tok_{secrets.token_urlsafe(32)}"
    device_token_hash = _hash_token(device_token)

    conn.execute(
        """INSERT INTO devices
           (device_id, device_name, platform, token_hash, app_version, created_at, last_seen_at, revoked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
           ON CONFLICT(device_id) DO UPDATE SET
               device_name = excluded.device_name,
               platform = excluded.platform,
               token_hash = excluded.token_hash,
               app_version = excluded.app_version,
               last_seen_at = excluded.last_seen_at,
               revoked_at = NULL""",
        (device_id, device_name, platform, device_token_hash, app_version, ts, ts),
    )
    conn.execute(
        "UPDATE enrollment_tokens SET used_at = ? WHERE token_hash = ?",
        (ts, enroll_hash),
    )

    seq_row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS max_seq FROM change_log").fetchone()
    current_seq = int(seq_row["max_seq"] if seq_row else 0)
    _audit(conn, device_id, "device-register", 200, ip_address=ip_address)
    conn.commit()

    return {
        "device_id": device_id,
        "device_token": device_token,
        "kdf_salt_hex": existing_salt,
        "key_check_value": existing_check or "",
        "server_time": now_epoch,
        "current_seq": current_seq,
    }


def _authenticate(conn, auth_header, ip_address=None):
    raw = str(auth_header or "").strip()
    if not raw.lower().startswith("bearer "):
        _audit(conn, None, "auth", 401, detail="missing_bearer", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Token autentikasi wajib disertakan", 401)
    token = raw[7:].strip()
    if not token:
        _audit(conn, None, "auth", 401, detail="empty_bearer", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Token autentikasi kosong", 401)
    token_hash = _hash_token(token)
    row = conn.execute(
        "SELECT * FROM devices WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    if not row:
        _audit(conn, None, "auth", 401, detail="unknown_token", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2001, "Token perangkat tidak valid", 401)
    if row["revoked_at"] is not None:
        _audit(conn, row["device_id"], "auth", 401, detail="device_revoked", ip_address=ip_address)
        conn.commit()
        raise SyncServerError(2002, "Akses perangkat telah dicabut", 401)
    conn.execute(
        "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
        (now_utc(), row["device_id"]),
    )
    return row


def _apply_entity_write(conn, entity_type, entity_uuid, operation, payload, new_revision, device_id, changed_at):
    created_at = payload.get("created_at") or changed_at
    updated_at = payload.get("updated_at") or changed_at
    deleted_at = payload.get("deleted_at")
    if operation in ("soft_delete", "purge") and not deleted_at:
        deleted_at = changed_at

    if entity_type == "group":
        conn.execute(
            """INSERT INTO sync_groups
               (uuid, title, sort, revision, created_at, updated_at, deleted_at, origin_device)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   title = excluded.title,
                   sort = excluded.sort,
                   revision = excluded.revision,
                   updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at,
                   origin_device = excluded.origin_device""",
            (
                entity_uuid,
                str(payload.get("title") or "Group"),
                int(payload.get("sort") or 0),
                new_revision,
                created_at,
                updated_at,
                deleted_at if operation != "upsert" else payload.get("deleted_at"),
                device_id,
            ),
        )
        row = conn.execute("SELECT * FROM sync_groups WHERE uuid = ?", (entity_uuid,)).fetchone()
        return _row_to_payload("group", row)

    if entity_type == "tag":
        conn.execute(
            """INSERT INTO sync_tags
               (uuid, title, revision, created_at, updated_at, deleted_at, origin_device)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   title = excluded.title,
                   revision = excluded.revision,
                   updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at,
                   origin_device = excluded.origin_device""",
            (
                entity_uuid,
                str(payload.get("title") or "Tag"),
                new_revision,
                created_at,
                updated_at,
                deleted_at if operation != "upsert" else payload.get("deleted_at"),
                device_id,
            ),
        )
        row = conn.execute("SELECT * FROM sync_tags WHERE uuid = ?", (entity_uuid,)).fetchone()
        return _row_to_payload("tag", row)

    if entity_type == "proxy":
        proxy_port = payload.get("proxy_port")
        if proxy_port in ("", None):
            proxy_port = None
        else:
            proxy_port = int(proxy_port)
        conn.execute(
            """INSERT INTO sync_proxies
               (uuid, proxy_type, proxy_ip, proxy_port, proxy_user, proxy_password_enc,
                proxy_fingerprint, note, tag, revision, created_at, updated_at, deleted_at, origin_device)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   proxy_type = excluded.proxy_type,
                   proxy_ip = excluded.proxy_ip,
                   proxy_port = excluded.proxy_port,
                   proxy_user = excluded.proxy_user,
                   proxy_password_enc = excluded.proxy_password_enc,
                   proxy_fingerprint = excluded.proxy_fingerprint,
                   note = excluded.note,
                   tag = excluded.tag,
                   revision = excluded.revision,
                   updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at,
                   origin_device = excluded.origin_device""",
            (
                entity_uuid,
                payload.get("proxy_type"),
                payload.get("proxy_ip"),
                proxy_port,
                payload.get("proxy_user"),
                payload.get("proxy_password_enc"),
                payload.get("proxy_fingerprint"),
                payload.get("note"),
                payload.get("tag"),
                new_revision,
                created_at,
                updated_at,
                deleted_at if operation != "upsert" else payload.get("deleted_at"),
                device_id,
            ),
        )
        row = conn.execute("SELECT * FROM sync_proxies WHERE uuid = ?", (entity_uuid,)).fetchone()
        return _row_to_payload("proxy", row)

    if entity_type == "template":
        conn.execute(
            """INSERT INTO sync_templates
               (uuid, name, payload, revision, created_at, updated_at, deleted_at, origin_device)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   name = excluded.name,
                   payload = excluded.payload,
                   revision = excluded.revision,
                   updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at,
                   origin_device = excluded.origin_device""",
            (
                entity_uuid,
                str(payload.get("name") or "Template"),
                _dumps_json(payload.get("payload"), "{}"),
                new_revision,
                created_at,
                updated_at,
                deleted_at if operation != "upsert" else payload.get("deleted_at"),
                device_id,
            ),
        )
        row = conn.execute("SELECT * FROM sync_templates WHERE uuid = ?", (entity_uuid,)).fetchone()
        return _row_to_payload("template", row)

    if entity_type == "extension":
        conn.execute(
            """INSERT INTO sync_extensions
               (uuid, slug, title, version, archive_blob_id, archive_sha256,
                revision, created_at, updated_at, deleted_at, origin_device)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uuid) DO UPDATE SET
                   slug = excluded.slug,
                   title = excluded.title,
                   version = excluded.version,
                   archive_blob_id = excluded.archive_blob_id,
                   archive_sha256 = excluded.archive_sha256,
                   revision = excluded.revision,
                   updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at,
                   origin_device = excluded.origin_device""",
            (
                entity_uuid,
                str(payload.get("slug") or entity_uuid),
                payload.get("title"),
                payload.get("version"),
                payload.get("archive_blob_id"),
                payload.get("archive_sha256"),
                new_revision,
                created_at,
                updated_at,
                deleted_at if operation != "upsert" else payload.get("deleted_at"),
                device_id,
            ),
        )
        row = conn.execute("SELECT * FROM sync_extensions WHERE uuid = ?", (entity_uuid,)).fetchone()
        return _row_to_payload("extension", row)

    if entity_type == "profile":
        if operation == "purge":
            purged_at = payload.get("purged_at") or changed_at
            blob_store = LocalFilesystemBlobStore(_server_db_path(conn))
            old_blobs = conn.execute(
                "SELECT blob_id FROM profile_blobs WHERE profile_uuid = ?",
                (entity_uuid,),
            ).fetchall()
            for b_row in old_blobs:
                blob_store.delete(b_row["blob_id"])
            conn.execute("DELETE FROM profile_blobs WHERE profile_uuid = ?", (entity_uuid,))
            conn.execute("DELETE FROM profile_leases WHERE profile_uuid = ?", (entity_uuid,))
            conn.execute(
                """INSERT INTO sync_profiles
                   (uuid, name, group_uuid, color, note, site_id, site_url,
                    proxy_config, proxy_fingerprint, fingerprint_config, preference_config,
                    tag_uuids, seed, last_open_time, cookie_blob_id, cookie_revision,
                    revision, created_at, updated_at, deleted_at, purged_at, origin_device)
                   VALUES (?, ?, ?, NULL, NULL, NULL, NULL, '{}', NULL, '{}', '{}', '[]', 1, NULL, NULL, 0, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(uuid) DO UPDATE SET
                       color = NULL,
                       note = NULL,
                       proxy_config = '{}',
                       proxy_fingerprint = NULL,
                       fingerprint_config = '{}',
                       preference_config = '{}',
                       tag_uuids = '[]',
                       cookie_blob_id = NULL,
                       revision = excluded.revision,
                       updated_at = excluded.updated_at,
                       deleted_at = COALESCE(sync_profiles.deleted_at, excluded.deleted_at),
                       purged_at = excluded.purged_at,
                       origin_device = excluded.origin_device""",
                (
                    entity_uuid,
                    str(payload.get("name") or "Deleted Profile"),
                    str(payload.get("group_uuid") or DEFAULT_GROUP_UUID),
                    new_revision,
                    created_at,
                    updated_at,
                    deleted_at,
                    purged_at,
                    device_id,
                ),
            )
            row = conn.execute("SELECT * FROM sync_profiles WHERE uuid = ?", (entity_uuid,)).fetchone()
            out = _row_to_payload("profile", row)
            if payload.get("group_title"):
                out["group_title"] = payload.get("group_title")
            if payload.get("tag_titles"):
                out["tag_titles"] = payload.get("tag_titles")
            return out

        existing = conn.execute(
            "SELECT * FROM sync_profiles WHERE uuid = ?", (entity_uuid,)
        ).fetchone()

        if operation == "soft_delete" and existing:
            conn.execute(
                """UPDATE sync_profiles
                   SET deleted_at = ?, updated_at = ?, revision = ?, origin_device = ?
                   WHERE uuid = ?""",
                (deleted_at, updated_at, new_revision, device_id, entity_uuid),
            )
        else:
            seed_val = int(payload.get("seed") or (existing["seed"] if existing else 1))
            conn.execute(
                """INSERT INTO sync_profiles
                   (uuid, name, group_uuid, color, note, site_id, site_url,
                    proxy_config, proxy_fingerprint, fingerprint_config, preference_config,
                    tag_uuids, seed, last_open_time, cookie_blob_id, cookie_revision,
                    revision, created_at, updated_at, deleted_at, purged_at, origin_device)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                   ON CONFLICT(uuid) DO UPDATE SET
                       name = excluded.name,
                       group_uuid = excluded.group_uuid,
                       color = excluded.color,
                       note = excluded.note,
                       site_id = excluded.site_id,
                       site_url = excluded.site_url,
                       proxy_config = excluded.proxy_config,
                       proxy_fingerprint = excluded.proxy_fingerprint,
                       fingerprint_config = excluded.fingerprint_config,
                       preference_config = excluded.preference_config,
                       tag_uuids = excluded.tag_uuids,
                       seed = excluded.seed,
                       last_open_time = excluded.last_open_time,
                       cookie_blob_id = COALESCE(excluded.cookie_blob_id, sync_profiles.cookie_blob_id),
                       cookie_revision = MAX(excluded.cookie_revision, sync_profiles.cookie_revision),
                       revision = excluded.revision,
                       updated_at = excluded.updated_at,
                       deleted_at = excluded.deleted_at,
                       purged_at = NULL,
                       origin_device = excluded.origin_device""",
                (
                    entity_uuid,
                    str(payload.get("name") or (existing["name"] if existing else "Profile")),
                    str(payload.get("group_uuid") or (existing["group_uuid"] if existing else DEFAULT_GROUP_UUID)),
                    payload.get("color"),
                    payload.get("note"),
                    payload.get("site_id") if payload.get("site_id") is not None else 22,
                    payload.get("site_url"),
                    _dumps_json(payload.get("proxy_config"), "{}"),
                    payload.get("proxy_fingerprint"),
                    _dumps_json(payload.get("fingerprint_config"), "{}"),
                    _dumps_json(payload.get("preference_config"), "{}"),
                    _dumps_json(payload.get("tag_uuids"), "[]"),
                    seed_val,
                    payload.get("last_open_time"),
                    payload.get("cookie_blob_id"),
                    int(payload.get("cookie_revision") or 0),
                    new_revision,
                    created_at,
                    updated_at,
                    deleted_at if operation == "soft_delete" else payload.get("deleted_at"),
                    device_id,
                ),
            )
        row = conn.execute("SELECT * FROM sync_profiles WHERE uuid = ?", (entity_uuid,)).fetchone()
        out = _row_to_payload("profile", row)
        if payload.get("group_title"):
            out["group_title"] = payload.get("group_title")
        if payload.get("tag_titles"):
            out["tag_titles"] = payload.get("tag_titles")
        return out

    raise SyncServerError(2003, f"Tipe entitas tidak dikenal: {entity_type}", 400)


TABLE_BY_ENTITY = {
    "group": "sync_groups",
    "tag": "sync_tags",
    "proxy": "sync_proxies",
    "template": "sync_templates",
    "extension": "sync_extensions",
    "profile": "sync_profiles",
}


def handle_push(conn, device, body, ip_address=None):
    mutations = body.get("mutations")
    if not isinstance(mutations, list):
        raise SyncServerError(2003, "mutations harus berupa array", 400)

    device_id = device["device_id"]
    results = []
    conn.execute("BEGIN IMMEDIATE")

    for item in mutations:
        if not isinstance(item, dict):
            raise SyncServerError(2003, "setiap mutasi harus berupa objek", 400)
        idem_key = str(item.get("idempotency_key") or "").strip()
        entity_type = str(item.get("entity_type") or "").strip()
        entity_uuid = str(item.get("entity_uuid") or "").strip()
        operation = str(item.get("operation") or "upsert").strip()
        base_revision = int(item.get("base_revision") or 0)
        client_updated_at = str(item.get("client_updated_at") or now_utc())
        payload = _loads_json(item.get("payload"), {})

        if not idem_key or not entity_type or not entity_uuid:
            raise SyncServerError(2003, "idempotency_key, entity_type, dan entity_uuid wajib diisi", 400)
        if entity_type not in TABLE_BY_ENTITY:
            raise SyncServerError(2003, f"entity_type tidak didukung: {entity_type}", 400)
        if operation not in ("upsert", "soft_delete", "purge"):
            raise SyncServerError(2003, f"operation tidak didukung: {operation}", 400)

        cached = conn.execute(
            "SELECT * FROM processed_mutations WHERE idempotency_key = ?",
            (idem_key,),
        ).fetchone()
        if cached:
            results.append(
                {
                    "idempotency_key": idem_key,
                    "entity_uuid": cached["entity_uuid"],
                    "status": cached["status"],
                    "new_revision": cached["new_revision"],
                    "seq": cached["seq"],
                    "conflict_id": cached["conflict_id"],
                    "merged_payload": _loads_json(cached["merged_payload"], None)
                    if cached["merged_payload"]
                    else None,
                }
            )
            continue

        table = TABLE_BY_ENTITY[entity_type]
        existing = conn.execute(
            f"SELECT * FROM {table} WHERE uuid = ?", (entity_uuid,)
        ).fetchone()
        server_revision = int(existing["revision"]) if existing else 0
        changed_at = now_utc()
        conflict_id = None
        merged_payload = None
        status = "applied"

        # Cek kasus edit pada profil yang sudah di-purge
        if (
            entity_type == "profile"
            and existing
            and existing["purged_at"] is not None
            and operation != "purge"
        ):
            conflict_id = f"conf_{secrets.token_hex(8)}"
            server_snap = _row_to_payload("profile", existing)
            conn.execute(
                """INSERT INTO conflicts
                   (conflict_id, entity_type, entity_uuid, base_revision, server_revision,
                    losing_device, winning_device, losing_payload, winning_payload, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PURGE_CONFLICT', ?)""",
                (
                    conflict_id,
                    entity_type,
                    entity_uuid,
                    base_revision,
                    server_revision,
                    device_id,
                    existing["origin_device"],
                    _dumps_json(payload),
                    _dumps_json(server_snap),
                    changed_at,
                ),
            )
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM change_log WHERE entity_type = ? AND entity_uuid = ?",
                (entity_type, entity_uuid),
            ).fetchone()
            seq = int(seq_row["s"] if seq_row else 0)
            status = "conflict_purged"
            merged_payload = server_snap
            conn.execute(
                """INSERT INTO processed_mutations
                   (idempotency_key, entity_uuid, status, new_revision, seq, conflict_id, merged_payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    idem_key,
                    entity_uuid,
                    status,
                    server_revision,
                    seq,
                    conflict_id,
                    _dumps_json(merged_payload),
                    changed_at,
                ),
            )
            results.append(
                {
                    "idempotency_key": idem_key,
                    "entity_uuid": entity_uuid,
                    "status": status,
                    "new_revision": server_revision,
                    "seq": seq,
                    "conflict_id": conflict_id,
                    "merged_payload": merged_payload,
                }
            )
            continue

        new_revision = server_revision + 1
        final_payload = dict(payload)

        if existing and base_revision < server_revision and operation == "upsert":
            server_snap = _row_to_payload(entity_type, existing)
            base_row = conn.execute(
                """SELECT payload FROM change_log
                   WHERE entity_type = ? AND entity_uuid = ? AND revision = ?
                   ORDER BY seq DESC LIMIT 1""",
                (entity_type, entity_uuid, base_revision),
            ).fetchone()
            base_snap = _loads_json(base_row["payload"], {}) if base_row else None
            final_payload, incoming_won = _merge_conflict_payload(
                entity_type,
                base_snap,
                server_snap,
                payload,
                existing["updated_at"],
                existing["origin_device"],
                client_updated_at,
                device_id,
            )
            if payload.get("group_title"):
                final_payload["group_title"] = payload.get("group_title")
            if payload.get("tag_titles"):
                final_payload["tag_titles"] = payload.get("tag_titles")

            conflict_id = f"conf_{secrets.token_hex(8)}"
            losing_dev = existing["origin_device"] if incoming_won else device_id
            winning_dev = device_id if incoming_won else existing["origin_device"]
            losing_pay = server_snap if incoming_won else payload
            conn.execute(
                """INSERT INTO conflicts
                   (conflict_id, entity_type, entity_uuid, base_revision, server_revision,
                    losing_device, winning_device, losing_payload, winning_payload, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'REVISION_MERGE_LWW', ?)""",
                (
                    conflict_id,
                    entity_type,
                    entity_uuid,
                    base_revision,
                    server_revision,
                    losing_dev,
                    winning_dev,
                    _dumps_json(losing_pay),
                    _dumps_json(final_payload),
                    changed_at,
                ),
            )
            status = "merged"

        saved_payload = _apply_entity_write(
            conn,
            entity_type,
            entity_uuid,
            operation,
            final_payload,
            new_revision,
            device_id,
            changed_at,
        )
        if status == "merged":
            merged_payload = saved_payload

        cur = conn.execute(
            """INSERT INTO change_log
               (entity_type, entity_uuid, operation, revision, origin_device, changed_at, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_type,
                entity_uuid,
                operation,
                new_revision,
                device_id,
                changed_at,
                _dumps_json(saved_payload),
            ),
        )
        seq = cur.lastrowid

        conn.execute(
            """INSERT INTO processed_mutations
               (idempotency_key, entity_uuid, status, new_revision, seq, conflict_id, merged_payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                idem_key,
                entity_uuid,
                status,
                new_revision,
                seq,
                conflict_id,
                _dumps_json(merged_payload) if merged_payload is not None else None,
                changed_at,
            ),
        )

        if operation == "purge":
            _audit(conn, device_id, f"{entity_type}-purge", 200, target_uuid=entity_uuid, ip_address=ip_address)

        results.append(
            {
                "idempotency_key": idem_key,
                "entity_uuid": entity_uuid,
                "status": status,
                "new_revision": new_revision,
                "seq": seq,
                "conflict_id": conflict_id,
                "merged_payload": merged_payload,
            }
        )

    conn.commit()
    return {"results": results}


def handle_pull(conn, device, body, ip_address=None):
    try:
        since_seq = max(0, int(body.get("since_seq") or 0))
        limit = min(500, max(1, int(body.get("limit") or 200)))
    except (TypeError, ValueError) as error:
        raise SyncServerError(2003, "since_seq dan limit harus berupa bilangan bulat", 400) from error

    rows = conn.execute(
        """SELECT seq, entity_type, entity_uuid, operation, revision,
                  origin_device, changed_at, payload
           FROM change_log
           WHERE seq > ?
           ORDER BY seq ASC
           LIMIT ?""",
        (since_seq, limit + 1),
    ).fetchall()

    has_more = len(rows) > limit
    sliced = rows[:limit]

    changes = []
    for row in sliced:
        changes.append(
            {
                "seq": row["seq"],
                "entity_type": row["entity_type"],
                "entity_uuid": row["entity_uuid"],
                "operation": row["operation"],
                "revision": row["revision"],
                "origin_device": row["origin_device"],
                "changed_at": row["changed_at"],
                "payload": _loads_json(row["payload"], {}),
            }
        )

    next_seq = changes[-1]["seq"] if changes else since_seq
    now_epoch = int(time.time())
    lease_rows = conn.execute(
        """SELECT l.profile_uuid, l.holder_device_id, d.device_name AS holder_device_name,
                  l.fencing_token, l.expires_at
           FROM profile_leases l
           LEFT JOIN devices d ON d.device_id = l.holder_device_id
           WHERE l.expires_at > ?""",
        (now_epoch,),
    ).fetchall()
    active_leases = [dict(r) for r in lease_rows]
    conn.commit()

    return {
        "changes": changes,
        "active_leases": active_leases,
        "next_seq": next_seq,
        "has_more": has_more,
    }


def handle_acquire_lease(conn, device, body, ip_address=None):
    profile_uuid = str(body.get("profile_uuid") or "").strip()
    if not profile_uuid:
        raise SyncServerError(2003, "profile_uuid wajib diisi", 400)
    force = bool(body.get("force", False))

    profile_row = conn.execute(
        "SELECT * FROM sync_profiles WHERE uuid = ?", (profile_uuid,)
    ).fetchone()
    if not profile_row:
        raise SyncServerError(404, 2003, "Profil tidak ditemukan")

    current_epoch = int(time.time())
    lease_row = conn.execute(
        "SELECT * FROM profile_leases WHERE profile_uuid = ?", (profile_uuid,)
    ).fetchone()
    last_fencing_token = int(profile_row["last_fencing_token"] or 0)
    if lease_row is not None:
        last_fencing_token = max(last_fencing_token, int(lease_row["fencing_token"] or 0))

    if (
        lease_row is not None
        and int(lease_row["expires_at"]) > current_epoch
        and lease_row["holder_device_id"] != device["device_id"]
        and not force
    ):
        holder_id = lease_row["holder_device_id"]
        dev_row = conn.execute(
            "SELECT device_name FROM devices WHERE device_id = ?", (holder_id,)
        ).fetchone()
        holder_name = (
            dev_row["device_name"]
            if dev_row and dev_row["device_name"]
            else holder_id
        )
        expires_at = int(lease_row["expires_at"])
        _audit(
            conn,
            device["device_id"],
            "lease_conflict",
            409,
            target_uuid=profile_uuid,
            ip_address=ip_address,
            detail=f"held_by={holder_id}",
        )
        conn.commit()
        raise SyncServerError(
            409,
            2004,
            f"Profil sedang dibuka di perangkat {holder_name}",
            {
                "holder_device_id": holder_id,
                "holder_device_name": holder_name,
                "expires_at": expires_at,
                "retry_after_seconds": max(1, expires_at - current_epoch),
            },
        )

    if (
        lease_row is not None
        and lease_row["holder_device_id"] == device["device_id"]
        and int(lease_row["expires_at"]) > current_epoch
        and not force
    ):
        expires_at = current_epoch + 60
        renewed_at = current_epoch
        conn.execute(
            """UPDATE profile_leases
               SET renewed_at = ?, expires_at = ?
               WHERE profile_uuid = ?""",
            (renewed_at, expires_at, profile_uuid),
        )
        lease_token = lease_row["lease_token"]
        fencing_token = int(lease_row["fencing_token"])
    else:
        fencing_token = last_fencing_token + 1
        lease_token = "ls_" + secrets.token_hex(16)
        expires_at = current_epoch + 60
        conn.execute(
            "UPDATE sync_profiles SET last_fencing_token = ? WHERE uuid = ?",
            (fencing_token, profile_uuid),
        )
        conn.execute(
            """INSERT OR REPLACE INTO profile_leases
               (profile_uuid, holder_device_id, lease_token, fencing_token, acquired_at, renewed_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_uuid,
                device["device_id"],
                lease_token,
                fencing_token,
                current_epoch,
                current_epoch,
                expires_at,
            ),
        )
        action = "force_takeover" if force else "lease_acquire"
        _audit(
            conn,
            device["device_id"],
            action,
            200,
            target_uuid=profile_uuid,
            ip_address=ip_address,
            detail=f"fencing_token={fencing_token}",
        )

    conn.commit()
    return {
        "profile_uuid": profile_uuid,
        "lease_token": lease_token,
        "fencing_token": fencing_token,
        "expires_at": expires_at,
        "latest_cookie_blob_id": profile_row["cookie_blob_id"],
        "latest_cookie_revision": int(profile_row["cookie_revision"] or 0),
    }


def handle_renew_lease(conn, device, body, ip_address=None):
    leases = body.get("leases")
    if leases is None:
        leases = []
    if not isinstance(leases, list):
        raise SyncServerError(2003, "leases harus berupa array", 400)

    current_epoch = int(time.time())
    renewed = []
    for entry in leases:
        if not isinstance(entry, dict):
            continue
        profile_uuid = str(entry.get("profile_uuid") or "").strip()
        lease_token = str(entry.get("lease_token") or "").strip()
        if not profile_uuid:
            continue
        row = conn.execute(
            """SELECT * FROM profile_leases
               WHERE profile_uuid = ? AND holder_device_id = ?""",
            (profile_uuid, device["device_id"]),
        ).fetchone()
        if row is not None and lease_token == row["lease_token"]:
            new_expires = current_epoch + 60
            conn.execute(
                """UPDATE profile_leases
                   SET renewed_at = ?, expires_at = ?
                   WHERE profile_uuid = ?""",
                (current_epoch, new_expires, profile_uuid),
            )
            renewed.append(
                {
                    "profile_uuid": profile_uuid,
                    "status": "ok",
                    "expires_at": new_expires,
                }
            )
        else:
            renewed.append(
                {
                    "profile_uuid": profile_uuid,
                    "status": "stolen",
                    "reason": "Lease telah kedaluwarsa atau diambil alih",
                }
            )

    conn.commit()
    return {"renewed": renewed}


def handle_release_lease(conn, device, body, ip_address=None):
    profile_uuid = str(body.get("profile_uuid") or "").strip()
    if not profile_uuid:
        raise SyncServerError(2003, "profile_uuid wajib diisi", 400)
    force = bool(body.get("force", False))

    if force:
        conn.execute(
            "DELETE FROM profile_leases WHERE profile_uuid = ?",
            (profile_uuid,),
        )
    else:
        conn.execute(
            "DELETE FROM profile_leases WHERE profile_uuid = ? AND holder_device_id = ?",
            (profile_uuid, device["device_id"]),
        )
    _audit(
        conn,
        device["device_id"],
        "lease_release",
        200,
        target_uuid=profile_uuid,
        ip_address=ip_address,
    )
    conn.commit()
    return {"released": True}


def handle_upload_blob(conn, device, body, ip_address=None):
    profile_uuid = str(body.get("profile_uuid") or "").strip()
    if not profile_uuid:
        raise SyncServerError(400, 2003, "profile_uuid wajib diisi")

    blob_kind = str(body.get("blob_kind") or "cookies").strip() or "cookies"
    if blob_kind not in ("cookies", "bookmarks", "extension_pkg", "snapshot"):
        raise SyncServerError(400, 2003, f"blob_kind tidak didukung: {blob_kind}")

    try:
        fencing_token = int(body.get("fencing_token") or 0)
    except (TypeError, ValueError) as error:
        raise SyncServerError(400, 2003, "fencing_token harus berupa bilangan bulat") from error

    encryption_scheme = (
        str(body.get("encryption_scheme") or "aes-256-gcm-v1").strip()
        or "aes-256-gcm-v1"
    )
    sha256_plain = str(body.get("sha256_plain") or "").strip()
    ciphertext_base64 = str(body.get("ciphertext_base64") or "").strip()
    if not sha256_plain or not ciphertext_base64:
        raise SyncServerError(
            400, 2003, "sha256_plain dan ciphertext_base64 wajib diisi"
        )

    sha256_cipher = (
        str(body.get("sha256_cipher") or "").strip()
        or hashlib.sha256(ciphertext_base64.encode("utf-8")).hexdigest()
    )
    try:
        size_bytes = int(body.get("size_bytes") or len(ciphertext_base64))
    except (TypeError, ValueError):
        size_bytes = len(ciphertext_base64)

    if size_bytes > MAX_COOKIE_BLOB_BYTES or len(ciphertext_base64) > MAX_COOKIE_BLOB_BYTES * 2:
        raise SyncServerError(413, 2010, "Ukuran blob melebihi batas maksimum 10 MB")

    profile_row = conn.execute(
        "SELECT * FROM sync_profiles WHERE uuid = ?", (profile_uuid,)
    ).fetchone()
    if not profile_row:
        raise SyncServerError(404, 2003, "Profil tidak ditemukan")

    last_fencing_token = int(profile_row["last_fencing_token"] or 0)
    if fencing_token < last_fencing_token:
        _audit(
            conn,
            device["device_id"],
            "blob_upload_stale_fence",
            409,
            target_uuid=profile_uuid,
            ip_address=ip_address,
            detail=f"fencing_token={fencing_token}<{last_fencing_token}",
        )
        conn.commit()
        raise SyncServerError(
            409,
            2006,
            f"Fencing token usang ({fencing_token} < {last_fencing_token})",
            {"current_fencing_token": last_fencing_token},
        )

    blob_store = LocalFilesystemBlobStore(_server_db_path(conn))
    active_blob_id = profile_row["cookie_blob_id"] if blob_kind == "cookies" else None
    if active_blob_id:
        active_row = conn.execute(
            """SELECT * FROM profile_blobs
               WHERE blob_id = ? AND profile_uuid = ? AND blob_kind = ?""",
            (active_blob_id, profile_uuid, blob_kind),
        ).fetchone()
        if (
            active_row is not None
            and active_row["sha256_plain"] == sha256_plain
            and blob_store.exists(active_blob_id)
        ):
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM change_log WHERE entity_uuid = ?",
                (profile_uuid,),
            ).fetchone()
            return {
                "blob_id": active_blob_id,
                "profile_uuid": profile_uuid,
                "cookie_revision": int(
                    profile_row["cookie_revision"] or active_row["revision"]
                ),
                "seq": int(seq_row["s"] if seq_row else 0),
            }

    current_cookie_revision = int(profile_row["cookie_revision"] or 0)
    cookie_revision = current_cookie_revision + 1
    if body.get("revision") is not None:
        try:
            client_rev = int(body.get("revision"))
        except (TypeError, ValueError):
            client_rev = cookie_revision
        if client_rev != cookie_revision:
            raise SyncServerError(
                409,
                2007,
                f"Revisi cookie belum sinkron ({client_rev} != {cookie_revision})",
                {"expected_revision": cookie_revision},
            )

    blob_id = f"blob_{secrets.token_hex(12)}"
    storage_key = blob_store.put(blob_id, ciphertext_base64.encode("utf-8"))
    now = now_utc()

    conn.execute(
        """UPDATE sync_profiles
           SET cookie_blob_id = ?,
               cookie_revision = ?,
               cookie_updated_at = ?,
               cookie_origin_device = ?,
               last_fencing_token = MAX(last_fencing_token, ?)
           WHERE uuid = ?""",
        (
            blob_id,
            cookie_revision,
            now,
            device["device_id"],
            fencing_token,
            profile_uuid,
        ),
    )

    conn.execute(
        """INSERT INTO profile_blobs
           (blob_id, profile_uuid, blob_kind, revision, sha256_plain, sha256_cipher,
            size_bytes, encryption_scheme, storage_key, created_at, origin_device)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            blob_id,
            profile_uuid,
            blob_kind,
            cookie_revision,
            sha256_plain,
            sha256_cipher,
            size_bytes,
            encryption_scheme,
            storage_key,
            now,
            device["device_id"],
        ),
    )

    change_payload = {
        "blob_id": blob_id,
        "cookie_revision": cookie_revision,
        "sha256_plain": sha256_plain,
        "sha256_cipher": sha256_cipher,
    }
    cur = conn.execute(
        """INSERT INTO change_log
           (entity_type, entity_uuid, operation, revision, origin_device, changed_at, payload)
           VALUES ('cookie_blob', ?, 'upsert', ?, ?, ?, ?)""",
        (
            profile_uuid,
            cookie_revision,
            device["device_id"],
            now,
            _dumps_json(change_payload),
        ),
    )
    seq = int(cur.lastrowid)

    blob_rows = conn.execute(
        """SELECT blob_id FROM profile_blobs
           WHERE profile_uuid = ? AND blob_kind = ?
           ORDER BY revision DESC""",
        (profile_uuid, blob_kind),
    ).fetchall()
    for stale_row in blob_rows[BLOB_RETENTION_COUNT:]:
        stale_blob_id = stale_row["blob_id"]
        blob_store.delete(stale_blob_id)
        conn.execute("DELETE FROM profile_blobs WHERE blob_id = ?", (stale_blob_id,))

    _audit(
        conn,
        device["device_id"],
        "blob_upload",
        200,
        target_uuid=profile_uuid,
        ip_address=ip_address,
        detail=f"blob_id={blob_id} rev={cookie_revision}",
    )
    conn.commit()
    return {
        "blob_id": blob_id,
        "profile_uuid": profile_uuid,
        "cookie_revision": cookie_revision,
        "seq": seq,
    }


def handle_download_blob(conn, device, body, ip_address=None):
    blob_id = str(body.get("blob_id") or "").strip()
    if not blob_id:
        raise SyncServerError(400, 2003, "blob_id wajib diisi")

    row = conn.execute(
        "SELECT * FROM profile_blobs WHERE blob_id = ?", (blob_id,)
    ).fetchone()
    if not row:
        raise SyncServerError(404, 2008, "Blob tidak ditemukan")

    blob_store = LocalFilesystemBlobStore(_server_db_path(conn))
    raw_bytes = blob_store.get(blob_id)
    ciphertext_base64 = raw_bytes.decode("utf-8", errors="replace")

    _audit(
        conn,
        device["device_id"],
        "blob_download",
        200,
        target_uuid=row["profile_uuid"],
        ip_address=ip_address,
        detail=f"blob_id={blob_id}",
    )
    conn.commit()
    return {
        "blob_id": blob_id,
        "profile_uuid": row["profile_uuid"],
        "blob_kind": row["blob_kind"],
        "revision": int(row["revision"]),
        "encryption_scheme": row["encryption_scheme"],
        "sha256_plain": row["sha256_plain"],
        "sha256_cipher": row["sha256_cipher"],
        "size_bytes": int(row["size_bytes"]),
        "ciphertext_base64": ciphertext_base64,
    }


class SyncHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, db_path=None):
        self.db_path = resolve_db_path(db_path)
        init_server_db(self.db_path)
        super().__init__(server_address, RequestHandlerClass)


class SyncRequestHandler(BaseHTTPRequestHandler):
    server_version = "antidetect-sync/0.1"

    def _route(self):
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _client_ip(self):
        return self.client_address[0] if self.client_address else None

    def _json(self, http_status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(http_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self._route()
        if route in ("/", "/health", "/v1/sync/health"):
            self._json(200, {"status": "ok"})
            return
        self._json(404, {"error": {"code": 404, "message": "not found"}, "data": None})

    def do_POST(self):
        route = self._route()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(body, dict):
                raise ValueError("Body harus berupa objek JSON")
        except (UnicodeDecodeError, ValueError):
            self._json(
                400,
                {"error": {"code": 2003, "message": "Body harus berupa objek JSON"}, "data": None},
            )
            return

        conn = connect_server_db(self.server.db_path)
        try:
            if route == "/v1/sync/device/register":
                data = handle_register_device(conn, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/push":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_push(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/pull":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_pull(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/lease/acquire":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_acquire_lease(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/lease/renew":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_renew_lease(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/lease/release":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_release_lease(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/blob/upload":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_upload_blob(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            if route == "/v1/sync/blob/download":
                device = _authenticate(conn, self.headers.get("Authorization"), ip_address=self._client_ip())
                data = handle_download_blob(conn, device, body, ip_address=self._client_ip())
                self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
                return

            self._json(404, {"error": {"code": 404, "message": "not found"}, "data": None})
        except SyncServerError as error:
            self._json(
                error.http_status,
                {"error": {"code": error.code, "message": error.message}, "data": error.data},
            )
        except Exception as error:
            self._json(
                500,
                {"error": {"code": 1000, "message": str(error)}, "data": None},
            )
        finally:
            conn.close()

    def log_message(self, fmt, *args):
        pass


def create_server(host="127.0.0.1", port=53210, data_dir=None, db_path=None):
    target_db = resolve_db_path(db_path if db_path is not None else data_dir)
    return SyncHTTPServer((host, int(port)), SyncRequestHandler, db_path=target_db)


def start_background_server(host="127.0.0.1", port=0, data_dir=None, db_path=None):
    httpd = create_server(host=host, port=port, data_dir=data_dir, db_path=db_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def serve(host="127.0.0.1", port=53210, data_dir=None, db_path=None):
    httpd = create_server(host=host, port=port, data_dir=data_dir, db_path=db_path)
    actual_host, actual_port = httpd.server_address[:2]
    print(f"antidetect sync-server listening on http://{actual_host}:{actual_port} (db: {httpd.db_path})")
    httpd.serve_forever()
