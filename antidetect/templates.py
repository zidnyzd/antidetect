"""Simpan dan pakai ulang template profil."""
import json

from . import store

TEMPLATE_LIMIT = 50
NAME_MAX = 80
DEFAULT_GROUP_ID = 1


class TemplateError(Exception):
    pass


def _decode(payload):
    try:
        data = json.loads(payload) if payload else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _snapshots(payload):
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        return []
    return [item for item in profiles if isinstance(item, dict)]


def _proxy_row_id(conn, proxy_config):
    """Cari baris proxies yang cocok dengan konfigurasi proxy profil."""
    proxy_type = str(proxy_config.get("proxy_type") or "direct").strip().lower()
    if proxy_type in ("", "none", "direct"):
        return None
    host = str(proxy_config.get("proxy_ip") or "").strip().lower()
    if not host:
        return None
    row = conn.execute(
        """SELECT id FROM proxies
           WHERE lower(COALESCE(proxy_type, '')) = ?
             AND lower(COALESCE(proxy_ip, '')) = ?
             AND COALESCE(proxy_port, 0) = COALESCE(?, 0)
           ORDER BY id LIMIT 1""",
        (proxy_type, host, proxy_config.get("proxy_port")),
    ).fetchone()
    return row["id"] if row else None


def _snapshot(conn, row):
    group_title = "Default"
    group = conn.execute(
        "SELECT title FROM groups WHERE id = ?", (row["group_id"],)
    ).fetchone()
    if group:
        group_title = group["title"]
    proxy_config = store._loads(row["proxy_config"])
    return {
        "name": row["name"],
        "fingerprint_config": store._loads(row["fingerprint_config"]),
        "proxy_config": proxy_config,
        "preference_config": store._loads(row["preference_config"]),
        "group_title": group_title,
        "note": row["note"],
        "color": row["color"],
        "proxy_id": _proxy_row_id(conn, proxy_config),
    }


def save_template(conn, profile_id, name, profile_ids=None):
    """Simpan template dari satu atau beberapa profil."""
    title = " ".join(str(name or "").split())
    if not title:
        raise TemplateError("Nama template wajib diisi")
    if len(title) > NAME_MAX:
        raise TemplateError(f"Nama template maksimal {NAME_MAX} karakter")
    if store.count_templates(conn) >= TEMPLATE_LIMIT:
        raise TemplateError(f"Maksimal {TEMPLATE_LIMIT} template tersimpan")
    if store.template_name_taken(conn, title):
        raise TemplateError("Nama template sudah dipakai")

    wanted = []
    if profile_ids:
        if not isinstance(profile_ids, list):
            profile_ids = [profile_ids]
        wanted = list(profile_ids)
    elif profile_id not in (None, ""):
        wanted = [profile_id]
    if not wanted:
        raise TemplateError("profile_id wajib diisi")

    snapshots = []
    for value in wanted:
        try:
            row = store.profile_get(conn, int(value))
        except (TypeError, ValueError):
            raise TemplateError("profile_id tidak valid")
        if not row or row["deleted_at"]:
            raise TemplateError("Profil tidak ditemukan")
        snapshots.append(_snapshot(conn, row))

    template_id = store.create_template(conn, title, {"profiles": snapshots})
    return {
        "id": template_id,
        "name": title,
        "profile_count": len(snapshots),
    }


def list_templates(conn, page=1, limit=10):
    total, rows = store.list_templates(conn, page=page, limit=limit)
    data = []
    for row in rows:
        payload = _decode(row["payload"])
        data.append(
            {
                "id": row["id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "profile_count": len(_snapshots(payload)),
            }
        )
    return {"total": total, "data": data}


def delete_template(conn, template_id):
    row = store.get_template(conn, template_id)
    if not row:
        raise TemplateError("Template tidak ditemukan")
    store.delete_template(conn, template_id)
    return {"id": int(template_id), "name": row["name"]}


def template_snapshot(conn, template_id, index=0):
    row = store.get_template(conn, template_id)
    if not row:
        raise TemplateError("Template tidak ditemukan")
    snapshots = _snapshots(_decode(row["payload"]))
    if not snapshots:
        raise TemplateError("Template tidak memuat profil")
    try:
        index = int(index or 0)
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(snapshots):
        raise TemplateError("Index profil di template tidak valid")
    return row, snapshots[index]


def _group_id(conn, title):
    text = str(title or "").strip()
    if text:
        row = conn.execute(
            "SELECT id FROM groups WHERE lower(title) = lower(?) ORDER BY id LIMIT 1",
            (text,),
        ).fetchone()
        if row:
            return row["id"]
    row = conn.execute(
        "SELECT id FROM groups WHERE lower(title) = 'default' ORDER BY id LIMIT 1"
    ).fetchone()
    return row["id"] if row else DEFAULT_GROUP_ID


def _proxy_config(conn, snapshot):
    """Proxy disalin hanya kalau baris proxy-nya masih ada."""
    config = snapshot.get("proxy_config") or {}
    proxy_id = snapshot.get("proxy_id")
    if proxy_id in (None, ""):
        return dict(config) if isinstance(config, dict) else {"proxy_type": "direct"}
    row = conn.execute(
        "SELECT id FROM proxies WHERE id = ?", (int(proxy_id),)
    ).fetchone()
    if row is None:
        return {"proxy_type": "direct"}
    return dict(config) if isinstance(config, dict) else {"proxy_type": "direct"}


def create_profile_from_template(conn, template_id, name, index=0):
    row, snapshot = template_snapshot(conn, template_id, index)
    profile_name = str(name or "").strip() or f"{row['name']} (template)"
    data = {
        "name": profile_name,
        "group_id": _group_id(conn, snapshot.get("group_title")),
        "color": snapshot.get("color"),
        "note": snapshot.get("note"),
        "proxy_config": _proxy_config(conn, snapshot),
        "fingerprint_config": snapshot.get("fingerprint_config") or {},
        "preference_config": snapshot.get("preference_config") or {},
    }
    profile_id = store.create_profile(conn, data)
    return {
        "profile_id": profile_id,
        "name": profile_name,
        "group_id": data["group_id"],
        "proxy_config": data["proxy_config"],
    }
