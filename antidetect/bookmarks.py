"""Read and edit the Chromium bookmark file of a profile."""
import hashlib
import json
import os
import tempfile
import time
import uuid
from urllib.parse import urlsplit

from . import launcher

ROOT_LABELS = {
    "bookmark_bar": "Bookmarks bar",
    "other": "Other bookmarks",
    "synced": "Mobile bookmarks",
}
ROOT_ORDER = ("bookmark_bar", "other", "synced")

# Chromium stores timestamps as microseconds since 1601-01-01.
_EPOCH_DELTA = 11644473600


class BookmarkError(Exception):
    pass


def _bookmark_path(profile_id):
    base = launcher.PROFILES_DIR / str(profile_id)
    candidates = (
        base / "data" / "Default" / "Bookmarks",
        base / "Default" / "Bookmarks",
        base / "data" / "Bookmarks",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _walk(children, folder, output):
    for child in children or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "folder":
            name = str(child.get("name") or "").strip()
            _walk(child.get("children"), f"{folder}/{name}" if name else folder, output)
            continue
        url = str(child.get("url") or "").strip()
        if not url:
            continue
        output.append(
            {
                "id": str(child.get("id") or len(output) + 1),
                "name": str(child.get("name") or url),
                "url": url,
                "folder": folder,
                "date_added": str(child.get("date_added") or ""),
            }
        )


def list_bookmarks(profile_id):
    """Return every URL bookmark as a flat row, folders included as labels."""
    path = _bookmark_path(profile_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BookmarkError(f"gagal membaca bookmark: {error}")
    except ValueError:
        raise BookmarkError("file bookmark rusak")

    roots = data.get("roots") if isinstance(data, dict) else None
    if not isinstance(roots, dict):
        return []
    items = []
    for key, node in roots.items():
        if not isinstance(node, dict):
            continue
        folder = str(node.get("name") or "").strip() or ROOT_LABELS.get(key, key)
        _walk(node.get("children"), folder, items)
    return items


def _empty_tree():
    return {
        "checksum": "",
        "roots": {
            key: {
                "children": [],
                "name": ROOT_LABELS[key],
                "type": "folder",
            }
            for key in ROOT_ORDER
        },
        "version": 1,
    }


def _load(path):
    if not path.is_file():
        return _empty_tree()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BookmarkError(f"gagal membaca bookmark: {error}")
    except ValueError:
        raise BookmarkError("file bookmark rusak")
    if not isinstance(data, dict):
        raise BookmarkError("file bookmark rusak")

    roots = data.get("roots")
    if not isinstance(roots, dict):
        roots = {}
        data["roots"] = roots
    for key in ROOT_ORDER:
        node = roots.get(key)
        if not isinstance(node, dict):
            roots[key] = {"children": [], "name": ROOT_LABELS[key], "type": "folder"}
            continue
        if not isinstance(node.get("children"), list):
            node["children"] = []
        if not node.get("name"):
            node["name"] = ROOT_LABELS[key]
        if not node.get("type"):
            node["type"] = "folder"
    data.setdefault("version", 1)
    data.setdefault("checksum", "")
    return data


def _require_closed(profile_id):
    if launcher.is_open(int(profile_id)):
        raise BookmarkError("tutup profil dulu")


def _now():
    return str(int((time.time() + _EPOCH_DELTA) * 1_000_000))


def _new_guid():
    return str(uuid.uuid4())


def _numeric_id(value):
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _subtree(node):
    yield node
    for child in node.get("children") or []:
        if isinstance(child, dict):
            yield from _subtree(child)


def _nodes(roots):
    for key in ROOT_ORDER:
        node = roots.get(key)
        if isinstance(node, dict):
            yield from _subtree(node)


def _ensure_ids(roots):
    """Give every node a unique positive numeric id and return the maximum."""
    nodes = list(_nodes(roots))
    used = set()
    duplicates = set()
    maximum = 0
    for node in nodes:
        value = _numeric_id(node.get("id"))
        if value is None:
            continue
        maximum = max(maximum, value)
        if value in used:
            duplicates.add(id(node))
        else:
            used.add(value)
    for node in nodes:
        if _numeric_id(node.get("id")) is None or id(node) in duplicates:
            maximum += 1
            node["id"] = str(maximum)
    return maximum


def _digest(algo, roots):
    """Mirror Chromium's checksum over id, UTF-16 title, type and URL."""
    digest = algo()

    def feed(value):
        digest.update(value if isinstance(value, bytes) else str(value).encode("utf-8"))

    def visit(node):
        name = str(node.get("name") or "")
        kind = str(node.get("type") or "")
        if kind not in ("url", "folder"):
            kind = "url" if node.get("url") else "folder"
        feed(str(node.get("id") or ""))
        feed(name.encode("utf-16-le"))
        feed(kind)
        if kind == "url":
            feed(str(node.get("url") or ""))
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for key in ROOT_ORDER:
        node = roots.get(key)
        if isinstance(node, dict):
            visit(node)
    return digest.hexdigest()


def _checksum(roots):
    return _digest(hashlib.md5, roots)


def _checksum_sha256(roots):
    return _digest(hashlib.sha256, roots)


def _save(path, data):
    data["checksum"] = _checksum(data["roots"])
    if "checksum_sha256" in data:
        data["checksum_sha256"] = _checksum_sha256(data["roots"])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=".Bookmarks-",
        delete=False,
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=3)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _clean_name(name):
    text = str(name or "").strip()
    if not text:
        raise BookmarkError("nama bookmark wajib diisi")
    if len(text) > 200:
        raise BookmarkError("nama bookmark maksimal 200 karakter")
    return text


def _clean_url(url):
    text = str(url or "").strip()
    if not text or any(char.isspace() for char in text):
        raise BookmarkError("URL wajib diisi tanpa spasi")
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise BookmarkError("URL harus http atau https dan memuat host")
    return text


def _folder_parts(folder):
    raw = str(folder or "").strip()
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    root = "bookmark_bar"
    if parts:
        lowered = parts[0].lower()
        for key, label in ROOT_LABELS.items():
            if lowered == label.lower():
                root = key
                parts = parts[1:]
                break
    return root, parts


def _folder_label(root, parts):
    label = ROOT_LABELS.get(root, root)
    return "/".join([label, *parts])


def add_bookmark(profile_id, name, url, folder=None):
    profile_id = int(profile_id)
    _require_closed(profile_id)
    name = _clean_name(name)
    url = _clean_url(url)
    root_key, parts = _folder_parts(folder)

    path = _bookmark_path(profile_id)
    data = _load(path)
    roots = data["roots"]
    next_id = _ensure_ids(roots) + 1

    node = roots[root_key]
    for part in parts:
        children = node["children"]
        existing = next(
            (
                child
                for child in children
                if isinstance(child, dict)
                and child.get("type") == "folder"
                and str(child.get("name") or "").strip() == part
            ),
            None,
        )
        if existing is None:
            stamp = _now()
            existing = {
                "children": [],
                "date_added": stamp,
                "date_last_used": "0",
                "date_modified": stamp,
                "guid": _new_guid(),
                "id": str(next_id),
                "name": part,
                "type": "folder",
            }
            next_id += 1
            children.append(existing)
        node = existing

    stamp = _now()
    bookmark = {
        "date_added": stamp,
        "date_last_used": "0",
        "guid": _new_guid(),
        "id": str(next_id),
        "name": name,
        "type": "url",
        "url": url,
    }
    node["children"].append(bookmark)
    _save(path, data)
    return {
        "id": bookmark["id"],
        "name": name,
        "url": url,
        "folder": _folder_label(root_key, parts),
    }


def delete_bookmark(profile_id, bookmark_id):
    profile_id = int(profile_id)
    _require_closed(profile_id)
    wanted = str(bookmark_id or "").strip()
    if not wanted:
        raise BookmarkError("bookmark_id wajib diisi")
    path = _bookmark_path(profile_id)
    if not path.is_file():
        raise BookmarkError("bookmark tidak ditemukan")
    data = _load(path)

    removed = None

    def prune(children):
        nonlocal removed
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            if child.get("url") and str(child.get("id") or "") == wanted:
                removed = children.pop(index)
                return True
            if child.get("type") == "folder" and prune(child.get("children") or []):
                return True
        return False

    for key in ROOT_ORDER:
        root = data["roots"][key]
        if prune(root["children"]):
            break
    if removed is None:
        raise BookmarkError("bookmark tidak ditemukan")

    _save(path, data)
    return {"id": wanted, "name": str(removed.get("name") or "")}
