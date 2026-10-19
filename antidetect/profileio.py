"""Export and import profile bundles as portable JSON."""
import base64
import json
import time

from . import cookies, launcher, store

VERSION = 1


class ProfileIOError(Exception):
    pass


def _timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def export_filename(name):
    safe = "".join(
        "-" if char in '\\/:*?"<>|' or ord(char) < 32 else char
        for char in str(name or "")
    )
    safe = " ".join(safe.split()).strip(" .")
    return f"profil-{safe or 'profil'}.json"


def export_profile(profile_id):
    profile_id = int(profile_id)
    with store.db() as conn:
        row = store.profile_get(conn, profile_id)
        if not row or row["deleted_at"]:
            raise ProfileIOError("profile not found")
        profile = store.profile_to_dict(row)
    profile.pop("deleted_at", None)
    try:
        cookie_text = cookies.get_cookies(profile_id)
    except cookies.CookieError as error:
        raise ProfileIOError(str(error))
    try:
        cookie_list = json.loads(cookie_text) if cookie_text else []
    except ValueError:
        cookie_list = []
    return {
        "version": VERSION,
        "exported_at": _timestamp(),
        "profile": profile,
        "cookies": cookie_list,
    }


def decode_content(content):
    raw = str(content or "").strip()
    if not raw:
        raise ProfileIOError("isi file kosong")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except (TypeError, ValueError):
        raise ProfileIOError("isi file bukan base64 yang valid")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ProfileIOError("file bukan JSON profil yang valid")


def _bundle(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ProfileIOError("bundle bukan JSON yang valid")
    if not isinstance(value, dict):
        raise ProfileIOError("bundle harus berupa objek JSON")
    return value


def _dict_field(value):
    return value if isinstance(value, dict) else {}


def _cookie_items(bundle):
    value = bundle.get("cookies")
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ProfileIOError("cookie pada bundle bukan JSON yang valid")
    if isinstance(value, dict) and "cookies" in value:
        value = value["cookies"]
    if not isinstance(value, list):
        raise ProfileIOError("cookie pada bundle harus berupa list")
    return value


def _unique_name(conn, name):
    candidate = f"{name} (impor)"
    index = 2
    while conn.execute(
        "SELECT 1 FROM profiles WHERE deleted_at IS NULL AND name = ?", (candidate,)
    ).fetchone():
        candidate = f"{name} (impor {index})"
        index += 1
    return candidate


def import_profile(bundle):
    """Create a new profile from an exported bundle and return it."""
    bundle = _bundle(bundle)
    try:
        version = int(bundle.get("version"))
    except (TypeError, ValueError):
        raise ProfileIOError("versi bundle tidak valid")
    if version != VERSION:
        raise ProfileIOError(f"versi bundle {version} tidak didukung")

    source = bundle.get("profile")
    if not isinstance(source, dict):
        raise ProfileIOError("bundle tidak memuat profil")
    name = str(source.get("name") or "").strip()
    if not name:
        raise ProfileIOError("profil pada bundle tidak punya nama")
    cookie_items = _cookie_items(bundle)

    with store.db() as conn:
        try:
            group_id = int(source.get("group_id"))
        except (TypeError, ValueError):
            group_id = 0
        if not conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone():
            group_id = 1
        profile_id = store.create_profile(
            conn,
            {
                "name": _unique_name(conn, name),
                "group_id": group_id,
                "color": source.get("color"),
                "note": source.get("note"),
                "site_id": source.get("site_id"),
                "site_url": source.get("site_url"),
                "proxy_config": _dict_field(source.get("proxy_config")),
                "fingerprint_config": _dict_field(source.get("fingerprint_config")),
                "preference_config": _dict_field(source.get("preference_config")),
                "tab_id": source.get("tab_id") or [],
                "seed": launcher.rand_seed(),
            },
        )

    if cookie_items:
        try:
            cookies.update_cookies(profile_id, cookie_items)
        except cookies.CookieError as error:
            with store.db() as conn:
                store.delete_profile_permanent(conn, profile_id)
            raise ProfileIOError(str(error))

    with store.db() as conn:
        return store.profile_to_dict(store.profile_get(conn, profile_id))
