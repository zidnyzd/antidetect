"""Agen sinkronisasi klien untuk antidetect (Push-Then-Pull)."""
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.request

from . import store, sync_crypto, sync_server

_orig_server_authenticate = getattr(sync_server, "_authenticate", None)
if callable(_orig_server_authenticate) and not getattr(
    _orig_server_authenticate, "_autocommit_wrapped", False
):
    def _wrapped_server_authenticate(conn, auth_header, ip_address=None):
        row = _orig_server_authenticate(conn, auth_header, ip_address=ip_address)
        if getattr(conn, "in_transaction", False):
            conn.commit()
        return row

    _wrapped_server_authenticate._autocommit_wrapped = True
    sync_server._authenticate = _wrapped_server_authenticate

ENTITY_TABLES = {
    "profile": "profiles",
    "group": "groups",
    "tag": "tags",
    "proxy": "proxies",
    "template": "templates",
    "extension": "extensions",
}


class SyncAgentError(Exception):
    def __init__(self, message, code=1000, http_status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _credentials_path(conn=None, db_path=None):
    if conn is not None:
        return store._conn_db_path(conn).parent / "sync_credentials.json"
    return store._resolve_db_path(db_path).parent / "sync_credentials.json"


def load_credentials(conn=None, db_path=None):
    path = _credentials_path(conn=conn, db_path=db_path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_credentials(creds, conn=None, db_path=None):
    path = _credentials_path(conn=conn, db_path=db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(creds, handle, ensure_ascii=False, indent=2)
    os.replace(str(tmp_path), str(path))
    os.chmod(str(path), 0o600)
    return path


def _post_json(url, payload, token=None, timeout=15):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            status_code = resp.status
    except urllib.error.HTTPError as error:
        raw_err = ""
        try:
            raw_err = error.read().decode("utf-8", errors="replace")
            parsed_err = json.loads(raw_err)
        except Exception:
            parsed_err = None
        if isinstance(parsed_err, dict) and isinstance(parsed_err.get("error"), dict):
            err_info = parsed_err["error"]
            raise SyncAgentError(
                err_info.get("message") or f"HTTP {error.code}",
                code=int(err_info.get("code") or error.code),
                http_status=error.code,
            ) from error
        raise SyncAgentError(
            raw_err or f"HTTP {error.code}",
            code=error.code,
            http_status=error.code,
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SyncAgentError(f"Gagal menghubungi server sinkronisasi: {error}", code=1000) from error

    if not isinstance(parsed, dict):
        raise SyncAgentError("Respons server bukan objek JSON", code=2003, http_status=status_code)
    err_obj = parsed.get("error") or {}
    err_code = int(err_obj.get("code") or 0)
    if err_code != 0:
        raise SyncAgentError(
            err_obj.get("message") or "Operasi sinkronisasi gagal",
            code=err_code,
            http_status=status_code,
        )
    return parsed.get("data") or {}


def _resolve_endpoint(conn, server_url=None, token=None):
    creds = load_credentials(conn=conn)
    resolved_url = (
        server_url
        or creds.get("server_url")
        or store.get_sync_state(conn, "server_url")
        or ""
    ).strip().rstrip("/")
    resolved_token = (
        token
        or creds.get("device_token")
        or store.get_sync_state(conn, "device_token")
        or ""
    ).strip()
    if not resolved_url:
        raise SyncAgentError("URL server sinkronisasi belum dikonfigurasi")
    if not resolved_token:
        raise SyncAgentError("Token perangkat sinkronisasi belum dikonfigurasi")
    return resolved_url, resolved_token


def register_device(server_url, enrollment_token, device_name, passphrase, db_path=None):
    clean_url = str(server_url or "").strip().rstrip("/")
    if not clean_url:
        raise SyncAgentError("server_url wajib diisi", code=2003)
    if not enrollment_token:
        raise SyncAgentError("enrollment_token wajib diisi", code=2003)
    if not passphrase:
        raise SyncAgentError("passphrase wajib diisi", code=2003)

    store.init(db_path=db_path)
    with store.db(db_path=db_path) as conn:
        device_id = store.get_device_id(conn)
        clean_name = str(device_name or socket.gethostname() or "Device").strip()
        data = _post_json(
            f"{clean_url}/v1/sync/device/register",
            {
                "enrollment_token": str(enrollment_token).strip(),
                "device_id": device_id,
                "device_name": clean_name,
                "platform": sys.platform,
                "app_version": "0.1.0",
                "passphrase": str(passphrase),
            },
        )
        registered_device_id = data.get("device_id") or device_id
        device_token = data["device_token"]
        salt_hex = data["kdf_salt_hex"]
        key_check = data.get("key_check_value") or ""

        kek = sync_crypto.derive_kek(passphrase, salt_hex)
        if key_check and not sync_crypto.verify_passphrase(passphrase, salt_hex, key_check):
            raise SyncAgentError("Frasa sandi sinkronisasi tidak cocok dengan server", code=2001)
        if not key_check:
            key_check = sync_crypto.compute_key_check(kek)
        dedupe_key = sync_crypto.derive_dedupe_key(kek)

        creds = {
            "server_url": clean_url,
            "device_id": registered_device_id,
            "device_name": clean_name,
            "device_token": device_token,
            "kdf_salt_hex": salt_hex,
            "key_check_value": key_check,
            "kek_hex": kek.hex(),
            "dedupe_key_hex": dedupe_key.hex(),
        }
        creds_path = save_credentials(creds, conn=conn, db_path=db_path)

        store.set_sync_state(conn, "device_id", registered_device_id)
        store.set_sync_state(conn, "device_name", clean_name)
        store.set_sync_state(conn, "server_url", clean_url)
        store.set_sync_state(conn, "device_token", device_token)
        store.set_sync_state(conn, "kdf_salt_hex", salt_hex)
        store.set_sync_state(conn, "key_check_value", key_check)
        if store.get_sync_state(conn, "last_pulled_seq") is None:
            store.set_sync_state(conn, "last_pulled_seq", "0")
        conn.commit()

    return {
        "device_id": registered_device_id,
        "device_name": clean_name,
        "device_token": device_token,
        "server_url": clean_url,
        "kdf_salt_hex": salt_hex,
        "key_check_value": key_check,
        "current_seq": int(data.get("current_seq") or 0),
        "credentials_path": str(creds_path),
    }


def _prepare_outbox_payload(conn, entity_type, raw_payload, kek, dedupe_key):
    payload = store._loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload or {})
    if entity_type == "proxy":
        if dedupe_key and not payload.get("proxy_fingerprint"):
            fp_src = dict(payload)
            if "proxy_password" not in fp_src and payload.get("uuid"):
                row = conn.execute(
                    "SELECT proxy_password FROM proxies WHERE uuid = ?",
                    (payload["uuid"],),
                ).fetchone()
                if row and row["proxy_password"] is not None:
                    fp_src["proxy_password"] = row["proxy_password"]
            payload["proxy_fingerprint"] = sync_crypto.proxy_fingerprint(fp_src, dedupe_key)
        if kek:
            if "proxy_password" not in payload and "proxy_password_enc" not in payload and payload.get("uuid"):
                row = conn.execute(
                    "SELECT proxy_password FROM proxies WHERE uuid = ?",
                    (payload["uuid"],),
                ).fetchone()
                if row and row["proxy_password"] is not None:
                    payload["proxy_password"] = row["proxy_password"]
            payload = sync_crypto.encrypt_proxy_config(payload, kek)
    elif entity_type == "profile":
        p_cfg = payload.get("proxy_config")
        if isinstance(p_cfg, dict):
            raw_cfg = dict(p_cfg)
            if "proxy_password" not in raw_cfg and "proxy_password_enc" not in raw_cfg and payload.get("uuid"):
                row = conn.execute(
                    "SELECT proxy_config FROM profiles WHERE uuid = ?",
                    (payload["uuid"],),
                ).fetchone()
                if row:
                    stored_cfg = store._loads(row["proxy_config"])
                    if "proxy_password" in stored_cfg:
                        raw_cfg["proxy_password"] = stored_cfg["proxy_password"]
            if dedupe_key and not payload.get("proxy_fingerprint"):
                payload["proxy_fingerprint"] = sync_crypto.proxy_fingerprint(raw_cfg, dedupe_key)
            if kek:
                payload["proxy_config"] = sync_crypto.encrypt_proxy_config(raw_cfg, kek)
    return payload


def _update_local_revision(conn, entity_type, entity_uuid, new_revision):
    table = ENTITY_TABLES.get(entity_type)
    if not table:
        return
    remaining = conn.execute(
        "SELECT 1 FROM sync_outbox WHERE entity_type = ? AND entity_uuid = ? LIMIT 1",
        (entity_type, entity_uuid),
    ).fetchone()
    dirty = 1 if remaining else 0
    conn.execute(
        f"UPDATE {table} SET revision = ?, sync_dirty = ? WHERE uuid = ?",
        (int(new_revision), dirty, entity_uuid),
    )


def push_outbox(conn, server_url=None, token=None, batch_size=50):
    store._ensure_sync_schema(conn)
    store.enqueue_dirty_entities(conn)
    resolved_url, resolved_token = _resolve_endpoint(conn, server_url, token)
    kek, dedupe_key = store._load_local_crypto(conn)

    batch_size = max(1, min(int(batch_size or 50), 100))
    total_pushed = 0
    total_applied = 0
    all_results = []

    for _ in range(100):
        rows = conn.execute(
            """SELECT * FROM sync_outbox
               ORDER BY CASE entity_type
                   WHEN 'group' THEN 1
                   WHEN 'tag' THEN 2
                   WHEN 'proxy' THEN 3
                   WHEN 'template' THEN 4
                   WHEN 'extension' THEN 5
                   WHEN 'profile' THEN 6
                   ELSE 7
               END ASC, outbox_id ASC
               LIMIT ?""",
            (batch_size,),
        ).fetchall()
        if not rows:
            break

        mutations = []
        by_idem = {}
        for row in rows:
            by_idem[row["idempotency_key"]] = row
            payload = _prepare_outbox_payload(
                conn, row["entity_type"], row["payload"], kek, dedupe_key
            )
            mutations.append(
                {
                    "idempotency_key": row["idempotency_key"],
                    "entity_type": row["entity_type"],
                    "entity_uuid": row["entity_uuid"],
                    "operation": row["operation"],
                    "base_revision": int(row["base_revision"] or 0),
                    "client_updated_at": payload.get("updated_at") or row["created_at"],
                    "payload": payload,
                }
            )

        try:
            data = _post_json(
                f"{resolved_url}/v1/sync/push",
                {"mutations": mutations},
                token=resolved_token,
            )
        except SyncAgentError as error:
            now_epoch = int(time.time())
            for row in rows:
                attempts = int(row["attempts"] or 0) + 1
                retry_at = now_epoch + min(300, 2 ** min(attempts, 8))
                conn.execute(
                    """UPDATE sync_outbox
                       SET attempts = ?, next_retry_at = ?, last_error = ?
                       WHERE outbox_id = ?""",
                    (attempts, retry_at, str(error), row["outbox_id"]),
                )
            store.set_sync_state(conn, "last_sync_error", str(error))
            conn.commit()
            raise

        results = data.get("results") or []
        total_pushed += len(rows)

        for res in results:
            all_results.append(res)
            idem_key = res.get("idempotency_key")
            status = res.get("status")
            new_rev = int(res.get("new_revision") or 1)
            outbox_row = by_idem.get(idem_key)
            if not outbox_row:
                continue

            entity_type = outbox_row["entity_type"]
            entity_uuid = outbox_row["entity_uuid"]

            if status in ("applied", "merged", "conflict_purged"):
                conn.execute(
                    "DELETE FROM sync_outbox WHERE idempotency_key = ?", (idem_key,)
                )
                _update_local_revision(conn, entity_type, entity_uuid, new_rev)
                if status == "applied":
                    total_applied += 1
                else:
                    total_applied += 1
                    conflict_id = res.get("conflict_id")
                    merged_payload = res.get("merged_payload")
                    if conflict_id:
                        conn.execute(
                            """INSERT OR REPLACE INTO local_conflicts
                               (conflict_id, entity_type, entity_uuid, reason,
                                losing_payload, winning_payload, resolved, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                            (
                                conflict_id,
                                entity_type,
                                entity_uuid,
                                status.upper(),
                                outbox_row["payload"],
                                json.dumps(merged_payload or {}, ensure_ascii=False),
                                store.now_utc(),
                            ),
                        )
                    if merged_payload is not None:
                        op = "purge" if status == "conflict_purged" else "upsert"
                        store.apply_remote_change(
                            conn,
                            {
                                "entity_type": entity_type,
                                "entity_uuid": entity_uuid,
                                "operation": op,
                                "revision": new_rev,
                                "origin_device": store.get_device_id(conn),
                                "changed_at": store.now_utc(),
                                "payload": merged_payload,
                            },
                        )

        conn.commit()
        if len(rows) < batch_size:
            break

    return {
        "pushed": total_pushed,
        "applied": total_applied,
        "results": all_results,
    }


def pull_changes(conn, server_url=None, token=None, limit=100):
    store._ensure_sync_schema(conn)
    resolved_url, resolved_token = _resolve_endpoint(conn, server_url, token)
    limit = max(1, min(int(limit or 100), 500))

    total_pulled = 0
    all_changes = []
    current_seq = int(store.get_sync_state(conn, "last_pulled_seq", "0") or 0)

    for _ in range(100):
        data = _post_json(
            f"{resolved_url}/v1/sync/pull",
            {"since_seq": current_seq, "limit": limit},
            token=resolved_token,
        )
        changes = data.get("changes") or []
        next_seq = int(
            data.get("next_seq") if data.get("next_seq") is not None else current_seq
        )
        has_more = bool(data.get("has_more"))

        for change in changes:
            store.apply_remote_change(conn, change)
            all_changes.append(change)
            total_pulled += 1

        active_leases = data.get("active_leases")
        if isinstance(active_leases, list):
            local_dev = store.get_device_id(conn)
            conn.execute("DELETE FROM local_leases WHERE is_local_holder = 0")
            for lease in active_leases:
                holder = lease.get("holder_device_id") or ""
                conn.execute(
                    """INSERT OR REPLACE INTO local_leases
                       (profile_uuid, holder_device_id, holder_device_name,
                        lease_token, fencing_token, expires_at, is_local_holder)
                       VALUES (?, ?, ?, NULL, ?, ?, ?)""",
                    (
                        lease.get("profile_uuid"),
                        holder,
                        lease.get("holder_device_name"),
                        int(lease.get("fencing_token") or 0),
                        int(lease.get("expires_at") or 0),
                        1 if holder == local_dev else 0,
                    ),
                )

        current_seq = next_seq
        store.set_sync_state(conn, "last_pulled_seq", str(current_seq))
        conn.commit()

        if not has_more or not changes:
            break

    store.set_sync_state(conn, "last_sync_at", store.now_utc())
    store.set_sync_state(conn, "last_sync_error", "")
    conn.commit()

    return {
        "pulled": total_pulled,
        "last_pulled_seq": current_seq,
        "changes": all_changes,
    }


def sync_cycle(conn=None, server_url=None, token=None):
    if conn is None:
        store.init()
        with store.db() as local_conn:
            return sync_cycle(local_conn, server_url=server_url, token=token)

    push_res = push_outbox(conn, server_url=server_url, token=token)
    pull_res = pull_changes(conn, server_url=server_url, token=token)
    return {
        "push": push_res,
        "pull": pull_res,
        "pushed": push_res["pushed"],
        "pulled": pull_res["pulled"],
        "last_pulled_seq": pull_res["last_pulled_seq"],
    }


def get_status(conn=None, db_path=None):
    if conn is None:
        store.init(db_path=db_path)
        with store.db(db_path=db_path) as local_conn:
            return get_status(local_conn, db_path=db_path)

    store._ensure_sync_schema(conn)
    creds = load_credentials(conn=conn, db_path=db_path)
    outbox_count = conn.execute("SELECT COUNT(*) AS c FROM sync_outbox").fetchone()["c"]
    device_id = creds.get("device_id") or store.get_sync_state(conn, "device_id") or ""
    device_name = creds.get("device_name") or store.get_sync_state(conn, "device_name") or ""
    server_url = creds.get("server_url") or store.get_sync_state(conn, "server_url") or ""
    last_pulled_seq = int(store.get_sync_state(conn, "last_pulled_seq", "0") or 0)
    last_sync_at = store.get_sync_state(conn, "last_sync_at") or None
    last_sync_error = store.get_sync_state(conn, "last_sync_error") or None
    return {
        "configured": bool(server_url and (creds.get("device_token") or store.get_sync_state(conn, "device_token"))),
        "device_id": device_id,
        "device_name": device_name,
        "server_url": server_url,
        "outbox_count": int(outbox_count),
        "last_pulled_seq": last_pulled_seq,
        "last_sync_at": last_sync_at,
        "last_sync_error": last_sync_error,
    }
