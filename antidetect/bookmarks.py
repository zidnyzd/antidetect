"""Flat bookmark listing from a Chromium profile."""
import json

from . import launcher

ROOT_LABELS = {
    "bookmark_bar": "Bookmarks bar",
    "other": "Other bookmarks",
    "synced": "Mobile bookmarks",
}


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
            _walk(child.get("children"), name or folder, output)
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
