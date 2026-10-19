"""Local extension storage: upload, list, delete unpacked Chromium extensions."""
import base64
import io
import json
import os
import secrets
import shutil
import struct
import zipfile
from pathlib import Path

from . import store
from .paths import DATA_DIR

EXTENSIONS_DIR = DATA_DIR / "extensions"
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
CRX_MAGIC = b"Cr24"


class ExtensionError(Exception):
    pass


def _slugify(name):
    slug = "".join(char if char.isalnum() else "-" for char in str(name or "").lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "extension"


def _unique_slug(base):
    with store.db() as conn:
        taken = {row["slug"] for row in conn.execute("SELECT slug FROM extensions")}
    slug = base
    index = 2
    while slug in taken or (EXTENSIONS_DIR / slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


def _decode(content):
    raw = str(content or "").strip()
    if not raw:
        raise ExtensionError("isi file extension kosong")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) > (MAX_UPLOAD_BYTES * 4) // 3 + 4:
        raise ExtensionError("ukuran extension melebihi 30 MB")
    try:
        data = base64.b64decode(raw, validate=False)
    except (ValueError, TypeError):
        raise ExtensionError("isi file bukan base64 yang valid")
    if not data:
        raise ExtensionError("isi file extension kosong")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtensionError("ukuran extension melebihi 30 MB")
    return data


def _zip_payload(filename, data):
    """Strip the CRX2/CRX3 header; plain zips are returned unchanged."""
    if data[:4] == CRX_MAGIC:
        if len(data) < 12:
            raise ExtensionError("header CRX tidak lengkap")
        version = struct.unpack("<I", data[4:8])[0]
        if version == 2:
            if len(data) < 16:
                raise ExtensionError("header CRX2 tidak lengkap")
            public_key_len, signature_len = struct.unpack("<II", data[8:16])
            offset = 16 + public_key_len + signature_len
        elif version == 3:
            header_len = struct.unpack("<I", data[8:12])[0]
            offset = 12 + header_len
        else:
            raise ExtensionError(f"versi CRX {version} tidak didukung")
        if offset >= len(data):
            raise ExtensionError("header CRX tidak sesuai ukuran file")
        data = data[offset:]
    elif str(filename or "").lower().endswith(".crx"):
        raise ExtensionError("file .crx tidak memakai header Cr24")
    if data[:2] != b"PK":
        raise ExtensionError("file bukan zip atau crx yang valid")
    return data


def _manifest_member(names):
    if "manifest.json" in names:
        return "manifest.json"
    tops = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(tops) == 1:
        wrapper = f"{next(iter(tops))}/manifest.json"
        if wrapper in names:
            return wrapper
    return None


def _read_manifest(archive, member):
    try:
        raw = archive.read(member)
    except KeyError:
        raise ExtensionError("manifest.json tidak bisa dibaca dari zip")
    except zipfile.BadZipFile:
        raise ExtensionError("zip rusak, manifest.json gagal dibaca")
    try:
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ExtensionError("manifest.json bukan JSON valid")
    if not isinstance(manifest, dict):
        raise ExtensionError("manifest.json harus berisi objek JSON")
    title = str(manifest.get("name") or "").strip()
    if not title:
        raise ExtensionError("manifest.json tidak memuat name")
    return title, str(manifest.get("version") or "").strip()


def _safe_parts(relative):
    parts = []
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." or part.endswith(":"):
            return None
        parts.append(part)
    return parts or None


def _extract(archive, member, target):
    prefix = member[: -len("manifest.json")]
    for info in archive.infolist():
        if not info.filename.startswith(prefix):
            continue
        relative = info.filename[len(prefix):]
        if not relative or relative.endswith("/"):
            continue
        parts = _safe_parts(relative)
        if parts is None:
            raise ExtensionError(f"entri zip tidak aman: {info.filename}")
        destination = target.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, open(destination, "wb") as handle:
            shutil.copyfileobj(source, handle)


def upload(filename, content):
    """Unpack a .zip/.crx upload into EXTENSIONS_DIR and register it."""
    data = _decode(content)
    payload = _zip_payload(filename, data)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        raise ExtensionError("file bukan zip yang valid")
    with archive:
        member = _manifest_member(archive.namelist())
        if member is None:
            raise ExtensionError("manifest.json tidak ditemukan di akar zip")
        title, version = _read_manifest(archive, member)
        slug = _unique_slug(_slugify(title))
        EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
        staging = EXTENSIONS_DIR / f".upload-{os.getpid()}-{secrets.token_hex(4)}"
        target = EXTENSIONS_DIR / slug
        try:
            _extract(archive, member, staging)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(staging), str(target))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    with store.db() as conn:
        cur = conn.execute(
            "INSERT INTO extensions (slug, title, version, path, created_at) VALUES (?,?,?,?,?)",
            (slug, title, version, str(target), store.now()),
        )
        conn.commit()
        extension_id = cur.lastrowid
    return {"id": extension_id, "slug": slug, "title": title, "version": version}


def _dir_size(folder):
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def list_extensions(page=1, limit=10, name=None):
    page = max(1, int(page or 1))
    limit = max(1, int(limit or 10))
    where, args = "", []
    if name:
        where = "WHERE title LIKE ?"
        args.append(f"%{name}%")
    with store.db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM extensions {where}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM extensions {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*args, limit, (page - 1) * limit],
        ).fetchall()
    data = []
    for row in rows:
        folder = Path(row["path"] or EXTENSIONS_DIR / row["slug"])
        data.append(
            {
                "id": row["id"],
                "title": row["title"],
                "version": row["version"],
                "slug": row["slug"],
                "path": str(folder),
                "size": _dir_size(folder),
                "created_at": row["created_at"],
            }
        )
    return {"total": total, "data": data}


def _profiles_using(conn, extension_id):
    users = []
    rows = conn.execute("SELECT id, name, preference_config FROM profiles ORDER BY id").fetchall()
    for row in rows:
        config = store._loads(row["preference_config"])
        ids = config.get("extension_ids") if isinstance(config, dict) else None
        if not isinstance(ids, list):
            continue
        try:
            used = {int(value) for value in ids}
        except (TypeError, ValueError):
            continue
        if extension_id in used:
            users.append(row["name"] or f"id {row['id']}")
    return users


def _inside_extensions(folder):
    try:
        Path(folder).resolve().relative_to(EXTENSIONS_DIR.resolve())
        return True
    except (OSError, ValueError):
        return False


def delete_extension(extension_id):
    try:
        extension_id = int(extension_id)
    except (TypeError, ValueError):
        raise ExtensionError("id extension tidak valid")
    with store.db() as conn:
        row = conn.execute("SELECT * FROM extensions WHERE id = ?", (extension_id,)).fetchone()
        if row is None:
            raise ExtensionError("Extension tidak ditemukan")
        users = _profiles_using(conn, extension_id)
        if users:
            raise ExtensionError(f"Extension masih dipakai profil {users[0]}")
        conn.execute("DELETE FROM extensions WHERE id = ?", (extension_id,))
        conn.commit()
    folder = Path(row["path"] or EXTENSIONS_DIR / row["slug"])
    if not _inside_extensions(folder):
        folder = EXTENSIONS_DIR / str(row["slug"] or "")
    shutil.rmtree(folder, ignore_errors=True)
    return True


def extension_paths(ids):
    """Resolve stored extension ids to unpacked folders that still exist."""
    wanted = []
    for value in ids or []:
        try:
            wanted.append(int(value))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return []
    placeholders = ",".join("?" for _ in wanted)
    with store.db() as conn:
        rows = conn.execute(
            f"SELECT id, path, slug FROM extensions WHERE id IN ({placeholders}) ORDER BY id",
            wanted,
        ).fetchall()
    paths = []
    for row in rows:
        folder = Path(row["path"] or EXTENSIONS_DIR / row["slug"])
        if folder.is_dir() and folder not in paths:
            paths.append(folder)
    return paths
