"""ixBrowser-compatible local API server (subset), stdlib only."""
import base64
import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    bookmarks,
    cookies,
    extensions,
    launcher,
    passwords,
    profileio,
    proxycheck,
    proxytext,
    store,
)

ACTIONS = {}


class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


def action(name):
    def wrap(fn):
        ACTIONS[name] = fn
        return fn
    return wrap


def _pid(params):
    pid = params.get("profile_id")
    if pid is None:
        raise ApiError(1001, "profile_id is required")
    return int(pid)


def _active_profile(conn, pid):
    row = store.profile_get(conn, pid)
    if not row or row["deleted_at"]:
        raise ApiError(1002, "profile not found")
    return row


def _event(kind, message, profile_id=None):
    """Best-effort local operation log; never break the main action."""
    try:
        with store.db() as conn:
            store.add_event(conn, kind, message, profile_id)
    except Exception:
        pass


def _profile_name(conn, pid):
    row = store.profile_get(conn, pid)
    return row["name"] if row else f"#{pid}"


def _proxy_label(data):
    host = str(data.get("proxy_ip") or "").strip()
    if host:
        port = data.get("proxy_port")
        return f"{host}:{port}" if port not in (None, "") else host
    note = str(data.get("note") or "").strip()
    if note:
        return note
    return f"#{data.get('id')}" if data.get("id") is not None else "tanpa alamat"


def _event_name(name, limit=80):
    text = " ".join(str(name or "").split()) or "tanpa nama"
    return text if len(text) <= limit else text[: limit - 3] + "..."


@action("engine-info")
def engine_info(params):
    kernels = [
        {**kernel, "supports": launcher.kernel_support(kernel["path"])}
        for kernel in launcher.available_kernels()
    ]
    return {
        "path": str(launcher.ENGINE_DIR),
        "version": kernels[0]["version"],
        "kernels": kernels,
    }


def _check_kernel_path(data):
    """Reject a profile kernel_path that is not an installed kernel."""
    preferences = data.get("preference_config")
    if not isinstance(preferences, dict):
        return
    raw = preferences.get("kernel_path")
    if raw in (None, ""):
        return
    try:
        chosen = str(Path(str(raw)).resolve())
    except (OSError, ValueError):
        chosen = ""
    available = {str(Path(kernel["path"]).resolve()) for kernel in launcher.available_kernels()}
    if chosen not in available:
        raise ApiError(1000, "kernel tidak tersedia")


def _check_preferences(data):
    try:
        launcher.validate_preferences(data.get("preference_config"))
    except launcher.PreferenceError as error:
        raise ApiError(1000, str(error))


@action("profile-reset-seed")
def profile_reset_seed(params):
    pid = _pid(params)
    if launcher.is_open(pid):
        raise ApiError(1004, "close the profile first")
    with store.db() as conn:
        row = _active_profile(conn, pid)
        name = row["name"]
        store.update_profile(conn, pid, {"seed": launcher.rand_seed()})
        seed = store.latest_seed(conn, pid)
    _event("profile-reset-seed", f'Seed profil "{_event_name(name)}" direset', pid)
    return {"profile_id": pid, "seed": seed}


@action("profile-list")
def profile_list(params):
    page = int(params.get("page") or 1)
    limit = int(params.get("limit") or 10)
    tag_id = params.get("tab_id", params.get("tag_id"))
    with store.db() as conn:
        total, rows = store.list_profiles(
            conn,
            page=page,
            limit=limit,
            group_id=params.get("group_id"),
            name=params.get("name"),
            profile_id=params.get("profile_id"),
            tag_id=tag_id,
        )
        return {"total": total, "data": [store.profile_to_dict(r) for r in rows]}


@action("profile-create")
def profile_create(params):
    _check_kernel_path(params)
    _check_preferences(params)
    with store.db() as conn:
        pid = store.create_profile(conn, params)
        name = _profile_name(conn, pid)
    _event("profile-create", f'Profil "{_event_name(name)}" dibuat', pid)
    return {"profile_id": pid, "new_profile_id": pid}


@action("profile-update")
def profile_update(params):
    pid = _pid(params)
    _check_kernel_path(params)
    _check_preferences(params)
    with store.db() as conn:
        _active_profile(conn, pid)
        store.update_profile(conn, pid, params)
        name = conn.execute("SELECT name FROM profiles WHERE id = ?", (pid,)).fetchone()["name"]
    _event("profile-update", f'Profil "{_event_name(name)}" diperbarui', pid)
    return True


@action("profile-delete")
def profile_delete(params):
    pid = _pid(params)
    launcher.close_profile(pid)
    with store.db() as conn:
        row = _active_profile(conn, pid)
        name = row["name"]
        store.soft_delete_profile(conn, pid)
    _event("profile-delete", f'Profil "{_event_name(name)}" dipindahkan ke keranjang sampah', pid)
    return True


@action("profile-recycle-list")
def profile_recycle_list(params):
    page = int(params.get("page") or 1)
    limit = int(params.get("limit") or 10)
    with store.db() as conn:
        total, rows = store.list_profiles(
            conn, page=page, limit=limit, name=params.get("name"), deleted=True
        )
        return {"total": total, "data": [store.profile_to_dict(r) for r in rows]}


@action("profile-restore")
def profile_restore(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row or not row["deleted_at"]:
            raise ApiError(1002, "profile not found")
        name = row["name"]
        store.restore_profile(conn, pid)
    _event("profile-restore", f'Profil "{_event_name(name)}" dipulihkan', pid)
    return True


@action("profile-delete-permanent")
def profile_delete_permanent(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row or not row["deleted_at"]:
            raise ApiError(1002, "profile not found")
        name = row["name"]
        store.delete_profile_permanent(conn, pid)
    _event("profile-delete-permanent", f'Profil "{_event_name(name)}" dihapus permanen', pid)
    return True


@action("profile-copy")
def profile_copy(params):
    pid = _pid(params)
    with store.db() as conn:
        row = _active_profile(conn, pid)
        source = row["name"]
        data = store.profile_to_dict(row)
        data.pop("profile_id")
        data.pop("seed", None)
        data["name"] = params.get("name") or f"{row['name']} copy"
        new_id = store.create_profile(conn, data)
        new_name = _profile_name(conn, new_id)
    _event(
        "profile-copy",
        f'Profil "{_event_name(source)}" disalin menjadi "{_event_name(new_name)}"',
        new_id,
    )
    return {"profile_id": new_id}


@action("profile-export")
def profile_export(params):
    pid = _known_pid(params)
    try:
        bundle = profileio.export_profile(pid)
        name = bundle["profile"].get("name") or pid
        password = str(params.get("password") or "")
        if password:
            bundle = profileio.encrypt_bundle(bundle, password)
    except profileio.ProfileIOError as error:
        raise ApiError(1004, str(error))
    content = json.dumps(bundle, ensure_ascii=False, indent=2).encode()
    _event("profile-export", f'Profil "{_event_name(name)}" diekspor', pid)
    filename = profileio.export_filename(name)
    if password:
        filename = filename[:-5] + ".enc.json"
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "encrypted": bool(password),
    }


@action("profile-import")
def profile_import(params):
    content = params.get("content_base64")
    try:
        if content not in (None, ""):
            bundle = profileio.decode_content(content)
        elif params.get("json") not in (None, ""):
            bundle = params.get("json")
        else:
            raise profileio.ProfileIOError("isi file profil kosong")
        if profileio.is_encrypted(bundle):
            password = str(params.get("password") or "")
            if not password:
                raise profileio.ProfileIOError("file profil terenkripsi, kata sandi wajib diisi")
            bundle = profileio.decrypt_bundle(bundle, password)
        created = profileio.import_profile(bundle)
    except profileio.ProfileIOError as error:
        raise ApiError(1000, str(error))
    _event(
        "profile-import",
        f'Profil "{_event_name(created.get("name"))}" diimpor',
        created.get("profile_id"),
    )
    return created


@action("profile-open")
def profile_open(params):
    pid = _pid(params)
    with store.db() as conn:
        row = _active_profile(conn, pid)
        profile = store.profile_to_dict(row, include_seed=True)
        name = row["name"]
    profile["id"] = pid
    try:
        result = launcher.open_profile(profile, app_args=params.get("args"))
    except launcher.LaunchError as error:
        raise ApiError(1003, str(error))
    with store.db() as conn:
        store.mark_opened(conn, pid)
    _event("profile-open", f'Profil "{_event_name(name)}" dibuka', pid)
    return result


@action("profile-open-with-random-fingerprint")
def profile_open_random(params):
    pid = _pid(params)
    with store.db() as conn:
        row = _active_profile(conn, pid)
        name = row["name"]
        profile = store.profile_to_dict(row, include_seed=True)
        fp = dict(profile["fingerprint_config"])
        fp.update(params.get("fingerprint_config") or {})
        proxy = params.get("proxy_config") or profile["proxy_config"]
        store.update_profile(
            conn,
            pid,
            {"fingerprint_config": fp, "proxy_config": proxy, "seed": launcher.rand_seed()},
        )
        profile["fingerprint_config"] = fp
        profile["proxy_config"] = proxy
        profile["seed"] = store.latest_seed(conn, pid)
    profile["id"] = pid
    try:
        result = launcher.open_profile(profile, app_args=params.get("args"))
    except launcher.LaunchError as error:
        raise ApiError(1003, str(error))
    with store.db() as conn:
        store.mark_opened(conn, pid)
    _event(
        "profile-open",
        f'Profil "{_event_name(name)}" dibuka dengan fingerprint acak',
        pid,
    )
    return result


@action("profile-close")
def profile_close(params):
    pid = _pid(params)
    launcher.close_profile(pid)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    _event("profile-close", f'Profil "{_event_name(name)}" ditutup', pid)
    return True


@action("profile-close-in-batches")
def profile_close_batches(params):
    ids = params.get("profile_id")
    if not isinstance(ids, list):
        ids = [ids]
    closed = []
    with store.db() as conn:
        for pid in ids:
            launcher.close_profile(int(pid))
            closed.append((int(pid), _profile_name(conn, int(pid))))
    for pid, name in closed:
        _event("profile-close", f'Profil "{_event_name(name)}" ditutup', pid)
    return True


def _id_list(params):
    ids = params.get("profile_id")
    if not isinstance(ids, list):
        ids = [ids]
    result = []
    for item in ids:
        try:
            value = int(item)
        except (TypeError, ValueError):
            raise ApiError(1000, "profile_id harus berupa daftar id")
        if value not in result:
            result.append(value)
    if not result:
        raise ApiError(1000, "profile_id tidak boleh kosong")
    return result


@action("profile-update-groups-in-batches")
def profile_update_groups_batches(params):
    ids = _id_list(params)
    group_id = params.get("group_id")
    if group_id in (None, ""):
        raise ApiError(1103, "Grup tidak ditemukan")
    group_id = int(group_id)
    with store.db() as conn:
        group = conn.execute("SELECT title FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise ApiError(1103, "Grup tidak ditemukan")
        for pid in ids:
            _active_profile(conn, pid)
        for pid in ids:
            store.update_profile(conn, pid, {"group_id": group_id})
    _event(
        "profile-update-groups-in-batches",
        f'{len(ids)} profil dipindahkan ke grup "{_event_name(group["title"])}"',
    )
    return True


BATCH_FIELDS = ("note", "color", "proxy_config", "fingerprint_config")


@action("profile-bookmark-add")
def profile_bookmark_add(params):
    pid = _known_pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    try:
        result = bookmarks.add_bookmark(
            pid, params.get("name"), params.get("url"), params.get("folder")
        )
    except bookmarks.BookmarkError as error:
        raise ApiError(1004, str(error))
    _event(
        "profile-bookmark-add",
        f'Bookmark "{_event_name(result["name"])}" ditambahkan ke profil "{_event_name(name)}"',
        pid,
    )
    return result


@action("profile-bookmark-delete")
def profile_bookmark_delete(params):
    pid = _known_pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    try:
        result = bookmarks.delete_bookmark(pid, params.get("bookmark_id"))
    except bookmarks.BookmarkError as error:
        raise ApiError(1004, str(error))
    _event(
        "profile-bookmark-delete",
        f'Bookmark "{_event_name(result["name"])}" dihapus dari profil "{_event_name(name)}"',
        pid,
    )
    return result


@action("profile-delete-saved-password")
def profile_delete_saved_password(params):
    pid = _known_pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    origin = str(params.get("origin_url") or "")
    try:
        result = passwords.delete_password(pid, origin, params.get("username"))
    except passwords.PasswordError as error:
        raise ApiError(1004, str(error))
    _event(
        "profile-delete-saved-password",
        f'Password {origin} profil "{_event_name(name)}" dihapus',
        pid,
    )
    return result


@action("profile-batch-update")
def profile_batch_update(params):
    ids = _id_list(params)
    data = {}
    if "note" in params:
        note = params.get("note")
        data["note"] = None if note is None else str(note)
    if "color" in params:
        data["color"] = params.get("color")
    for key in ("proxy_config", "fingerprint_config"):
        if key in params:
            value = params.get(key)
            if not isinstance(value, dict):
                raise ApiError(1000, f"{key} harus berupa objek")
            data[key] = value
    if not data:
        raise ApiError(1000, f"Tidak ada field untuk diubah, pilih salah satu dari {', '.join(BATCH_FIELDS)}")
    with store.db() as conn:
        for pid in ids:
            _active_profile(conn, pid)
        for pid in ids:
            store.update_profile(conn, pid, data)
    labels = {"note": "catatan", "color": "warna", "proxy_config": "proxy", "fingerprint_config": "fingerprint"}
    fields = ", ".join(labels[key] for key in data)
    _event("profile-batch-update", f"{len(ids)} profil diperbarui: {fields}")
    return {"updated": len(ids)}


@action("profile-opened-list")
def profile_opened_list(params):
    return launcher.opened_profiles()


@action("profile-opened-list-arrange-tile")
def profile_opened_list_arrange_tile(params):
    return launcher.arrange_opened_profiles(params)


@action("native-client-profile-opened-list")
def native_opened_list(params):
    return []


@action("profile-open-state-reset")
def profile_open_state_reset(params):
    launcher.forget(_pid(params))
    return True


@action("profile-random-fingerprint-configuration")
def profile_random_fingerprint(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row:
            raise ApiError(1002, "profile not found")
        seed = launcher.rand_seed()
        store.update_profile(conn, pid, {"seed": seed})
        return {"profile_id": pid, "fingerprint_config": store._loads(row["fingerprint_config"])}


def _known_pid(params):
    pid = _pid(params)
    with store.db() as conn:
        if not store.profile_get(conn, pid):
            raise ApiError(1002, "profile not found")
    return pid


@action("profile-get-cookies")
def profile_get_cookies(params):
    pid = _known_pid(params)
    try:
        return cookies.get_cookies(pid)
    except cookies.CookieError as error:
        raise ApiError(1004, str(error))


@action("profile-update-cookies")
def profile_update_cookies(params):
    pid = _known_pid(params)
    if "cookie" not in params:
        raise ApiError(1000, "cookie is required")
    with store.db() as conn:
        name = _profile_name(conn, pid)
    try:
        result = cookies.update_cookies(pid, params.get("cookie"))
    except cookies.CookieError as error:
        raise ApiError(1004, str(error))
    _event("profile-update-cookies", f'Cookie profil "{_event_name(name)}" diperbarui', pid)
    return result


@action("profile-clear-saved-user-password")
def profile_clear_saved_user_password(params):
    pid = _known_pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    try:
        result = cookies.clear_saved_passwords(pid)
    except cookies.CookieError as error:
        raise ApiError(1004, str(error))
    _event(
        "profile-clear-saved-user-password",
        f'Password tersimpan profil "{_event_name(name)}" dihapus',
        pid,
    )
    return result


@action("profile-bookmarks")
def profile_bookmarks(params):
    pid = _known_pid(params)
    try:
        return bookmarks.list_bookmarks(pid)
    except bookmarks.BookmarkError as error:
        raise ApiError(1004, str(error))


@action("profile-saved-passwords")
def profile_saved_passwords(params):
    pid = _known_pid(params)
    try:
        return passwords.list_saved_passwords(pid)
    except passwords.PasswordError as error:
        raise ApiError(1004, str(error))


def _clear_cache(pid, with_cookies=False):
    if launcher.is_open(pid):
        raise ApiError(1004, "close the profile first")
    default = launcher.PROFILES_DIR / str(pid) / "data" / "Default"
    for name in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
        shutil.rmtree(default / name, ignore_errors=True)
    if with_cookies:
        for name in ("Cookies", "Cookies-journal"):
            try:
                (default / name).unlink()
            except OSError:
                pass
    return True


@action("profile-clear-cache")
def profile_clear_cache(params):
    pid = _pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    result = _clear_cache(pid)
    _event("profile-clear-cache", f'Cache profil "{_event_name(name)}" dibersihkan', pid)
    return result


@action("profile-clear-cache-and-cookies")
def profile_clear_cache_cookies(params):
    pid = _pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    result = _clear_cache(pid, with_cookies=True)
    _event("profile-clear-cache-and-cookies", f'Cache dan cookie profil "{_event_name(name)}" dibersihkan', pid)
    return result


@action("profile-clear-cache-keep-extensions")
def profile_clear_cache_ext(params):
    pid = _pid(params)
    with store.db() as conn:
        name = _profile_name(conn, pid)
    result = _clear_cache(pid)
    _event(
        "profile-clear-cache-keep-extensions",
        f'Cache profil "{_event_name(name)}" dibersihkan, extension dipertahankan',
        pid,
    )
    return result


@action("empty-recycle-bin")
def empty_recycle_bin(params):
    with store.db() as conn:
        count = store.empty_recycle_bin(conn)
    _event("empty-recycle-bin", f"Keranjang sampah dikosongkan, {count} profil dihapus permanen")
    return {"count": count}


def _paginated(conn, table, page, limit):
    total = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM {table} ORDER BY id LIMIT ? OFFSET ?",
        (int(limit), (int(page) - 1) * int(limit)),
    ).fetchall()
    return {"total": total, "data": [dict(r) for r in rows]}


@action("group-list")
def group_list(params):
    with store.db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM groups").fetchone()["c"]
        rows = conn.execute(
            """SELECT id, title, sort, created_at,
                      (SELECT COUNT(*) FROM profiles
                        WHERE group_id = groups.id AND deleted_at IS NULL) AS profile_count
               FROM groups
               ORDER BY sort DESC, id ASC
               LIMIT ? OFFSET ?""",
            (
                int(params.get("limit") or 100),
                (int(params.get("page") or 1) - 1) * int(params.get("limit") or 100),
            ),
        ).fetchall()
        return {"total": total, "data": [dict(row) for row in rows]}


def _sort_value(params):
    try:
        return int(params.get("sort") or 0)
    except (TypeError, ValueError):
        raise ApiError(1000, "sort harus berupa bilangan bulat")


@action("group-create")
def group_create(params):
    title = str(params.get("title") or "").strip()
    if not title:
        raise ApiError(1101, "Nama grup wajib diisi")
    sort = _sort_value(params)
    with store.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        duplicate = conn.execute(
            "SELECT 1 FROM groups WHERE lower(title) = lower(?)", (title,)
        ).fetchone()
        if duplicate:
            raise ApiError(1102, "Nama grup sudah dipakai")
        cur = conn.execute(
            "INSERT INTO groups (title, sort, created_at) VALUES (?, ?, ?)",
            (title, sort, store.now()),
        )
        conn.commit()
        gid = cur.lastrowid
    _event("group-create", f'Grup "{_event_name(title)}" dibuat')
    return {"id": gid}


@action("group-update")
def group_update(params):
    gid = params.get("id")
    if gid is None:
        raise ApiError(1103, "Grup tidak ditemukan")
    gid = int(gid)
    with store.db() as conn:
        row = conn.execute("SELECT id FROM groups WHERE id = ?", (gid,)).fetchone()
        if not row:
            raise ApiError(1103, "Grup tidak ditemukan")

        fields, args = [], []
        if "title" in params:
            title = str(params.get("title") or "").strip()
            if not title:
                raise ApiError(1101, "Nama grup wajib diisi")
            duplicate = conn.execute(
                "SELECT 1 FROM groups WHERE lower(title) = lower(?) AND id <> ?", (title, gid)
            ).fetchone()
            if duplicate:
                raise ApiError(1102, "Nama grup sudah dipakai")
            fields.append("title = ?")
            args.append(title)
        if "sort" in params:
            fields.append("sort = ?")
            args.append(_sort_value(params))
        if fields:
            args.append(gid)
            conn.execute(f"UPDATE groups SET {', '.join(fields)} WHERE id = ?", args)
            conn.commit()
        title = conn.execute("SELECT title FROM groups WHERE id = ?", (gid,)).fetchone()["title"]
    _event("group-update", f'Grup "{_event_name(title)}" diperbarui')
    return True


@action("group-delete")
def group_delete(params):
    gid = params.get("id")
    if gid is None:
        raise ApiError(1103, "Grup tidak ditemukan")
    gid = int(gid)
    with store.db() as conn:
        row = conn.execute("SELECT id, title FROM groups WHERE id = ?", (gid,)).fetchone()
        if not row:
            raise ApiError(1103, "Grup tidak ditemukan")
        if gid == 1 or row["title"] == "Default":
            raise ApiError(1104, "Grup Default tidak bisa dihapus")
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM profiles WHERE group_id = ?", (gid,)
        ).fetchone()["c"]
        if count > 0:
            raise ApiError(
                1105,
                f"Grup masih berisi {count} profil (termasuk keranjang sampah), pindahkan dulu",
            )
        conn.execute("DELETE FROM groups WHERE id = ?", (gid,))
        conn.commit()
        title = row["title"]
    _event("group-delete", f'Grup "{_event_name(title)}" dihapus')
    return True


@action("tag-list")
def tag_list(params):
    with store.db() as conn:
        return _paginated(conn, "tags", params.get("page") or 1, params.get("limit") or 100)


@action("tag-create")
def tag_create(params):
    title = params.get("title") or "Tag"
    with store.db() as conn:
        cur = conn.execute("INSERT INTO tags (title) VALUES (?)", (title,))
        conn.commit()
        tid = cur.lastrowid
    _event("tag-create", f'Tag "{_event_name(title)}" dibuat')
    return {"id": tid}


@action("tag-update")
def tag_update(params):
    tid = int(params.get("id") or 0)
    title = params.get("title")
    with store.db() as conn:
        conn.execute("UPDATE tags SET title = ? WHERE id = ?", (title, tid))
        conn.commit()
    _event("tag-update", f'Tag "{_event_name(title)}" diperbarui')
    return True


@action("tag-delete")
def tag_delete(params):
    tid = int(params.get("id") or 0)
    with store.db() as conn:
        row = conn.execute("SELECT title FROM tags WHERE id = ?", (tid,)).fetchone()
        title = row["title"] if row else f"#{tid}"
        conn.execute("DELETE FROM tags WHERE id = ?", (tid,))
        conn.commit()
    _event("tag-delete", f'Tag "{_event_name(title)}" dihapus')
    return True


@action("proxy-list")
def proxy_list(params):
    with store.db() as conn:
        return _paginated(conn, "proxies", params.get("page") or 1, params.get("limit") or 10)


@action("proxy-import")
def proxy_import(params):
    try:
        result = proxytext.import_text(params.get("text"), params.get("default_type"))
    except proxytext.ProxyTextError as error:
        raise ApiError(1000, str(error))
    _event(
        "proxy-import",
        f"Impor proxy: {result['created']} dibuat, {result['skipped']} dilewati",
    )
    return result


@action("proxy-export")
def proxy_export(params):
    result = proxytext.export_proxies(params.get("include_credentials", False))
    _event("proxy-export", f"Ekspor {result['count']} proxy")
    return result


@action("proxy-create")
def proxy_create(params):
    with store.db() as conn:
        proxy_id = store.create_proxy(conn, params)
    _event("proxy-create", f'Proxy "{_event_name(_proxy_label(params))}" ditambahkan')
    return {"id": proxy_id}


@action("proxy-update")
def proxy_update(params):
    proxy_id = int(params.get("id") or 0)
    with store.db() as conn:
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        merged = dict(row) if row else {"id": proxy_id}
        merged.update({key: value for key, value in params.items() if value is not None})
        fields, args = [], []
        for key in ("proxy_type", "proxy_ip", "proxy_port", "proxy_user",
                    "proxy_password", "note", "tag"):
            if params.get(key) is not None:
                fields.append(f"{key} = ?")
                args.append(params[key])
        if fields:
            args.append(proxy_id)
            conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id = ?", args)
            conn.commit()
    _event("proxy-update", f'Proxy "{_event_name(_proxy_label(merged))}" diperbarui')
    return True


@action("proxy-delete")
def proxy_delete(params):
    proxy_id = int(params.get("id") or 0)
    with store.db() as conn:
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        label = _proxy_label(dict(row)) if row else f"#{proxy_id}"
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        conn.commit()
    _event("proxy-delete", f'Proxy "{_event_name(label)}" dihapus')
    return True


@action("proxy-check")
def proxy_check(params):
    return proxycheck.check_proxy(params)


@action("traffic-package-list")
def traffic_package_list(params):
    return {"total": 0, "data": []}


@action("extension-list")
def extension_list(params):
    try:
        return extensions.list_extensions(
            params.get("page") or 1,
            params.get("limit") or 10,
            str(params.get("name") or "").strip() or None,
        )
    except (TypeError, ValueError):
        raise ApiError(1200, "page dan limit harus berupa bilangan bulat")


@action("extension-upload")
def extension_upload(params):
    filename = params.get("filename") or params.get("file_name")
    content = params.get("content") or params.get("content_base64")
    try:
        result = extensions.upload(filename, content)
    except extensions.ExtensionError as error:
        raise ApiError(1201, str(error))
    _event(
        "extension-upload",
        f'Extension "{_event_name(result.get("title"))}" diunggah',
    )
    return result


@action("extension-delete")
def extension_delete(params):
    extension_id = params.get("id", params.get("extension_id"))
    if extension_id in (None, ""):
        raise ApiError(1200, "id extension wajib diisi")
    with store.db() as conn:
        row = conn.execute(
            "SELECT title FROM extensions WHERE id = ?", (int(extension_id),)
        ).fetchone()
        title = row["title"] if row else f"#{extension_id}"
    try:
        result = extensions.delete_extension(extension_id)
    except extensions.ExtensionError as error:
        raise ApiError(1202, str(error))
    _event("extension-delete", f'Extension "{_event_name(title)}" dihapus')
    return result


@action("gateway-list")
def gateway_list(params):
    return []


@action("proxy-tag-list")
def proxy_tag_list(params):
    return {"total": 0, "data": []}


@action("proxy-tag-create")
def proxy_tag_create(params):
    return True


@action("proxy-tag-update")
def proxy_tag_update(params):
    return True


@action("proxy-tag-delete")
def proxy_tag_delete(params):
    return True


@action("event-list")
def event_list(params):
    try:
        page = max(1, int(params.get("page") or 1))
        limit = min(2000, max(1, int(params.get("limit") or 20)))
    except (TypeError, ValueError):
        raise ApiError(1000, "page dan limit harus berupa bilangan bulat")
    with store.db() as conn:
        total, rows = store.list_events(conn, page=page, limit=limit, kind=params.get("kind"))
        return {"total": total, "data": [dict(row) for row in rows]}


@action("event-clear")
def event_clear(params):
    with store.db() as conn:
        return {"count": store.clear_events(conn)}


class Handler(BaseHTTPRequestHandler):
    server_version = "antidetect/0.1"

    def do_POST(self):
        if not self.path.startswith("/api/v2/"):
            self._json(404, {"error": {"code": 404, "message": "not found"}})
            return
        name = self.path[len("/api/v2/"):].strip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            params = json.loads(raw) if raw else {}
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            self._json(200, {"error": {"code": 1000, "message": "body must be a JSON object"}})
            return

        fn = ACTIONS.get(name)
        if fn is None:
            self._json(200, {"error": {"code": 1001, "message": f"unknown action: {name}"}})
            return
        try:
            data = fn(params)
            self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
        except ApiError as error:
            self._json(200, {"error": {"code": error.code, "message": error.message}})
        except Exception as error:
            self._json(200, {"error": {"code": 1000, "message": str(error)}})

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._json(200, {"status": "ok", "open": len(launcher.opened_profiles())})
            return
        self._json(404, {"error": {"code": 404, "message": "not found"}})

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return None
        extra = {
            item.strip().rstrip("/")
            for item in os.environ.get("ANTIDETECT_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        }
        if origin.rstrip("/") in extra:
            return origin
        try:
            parts = urlsplit(origin)
        except ValueError:
            return None
        if parts.scheme in ("http", "https") and parts.hostname in ("127.0.0.1", "localhost", "::1"):
            return origin
        return None

    def _send_cors_headers(self):
        origin = self._origin_allowed()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def serve(host="127.0.0.1", port=53200):
    store.init()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"antidetect API listening on http://{host}:{port}/api/v2/")
    httpd.serve_forever()
