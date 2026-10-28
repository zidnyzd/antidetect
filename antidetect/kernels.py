"""Siklus hidup kernel Chromium tambahan di KERNELS_DIR.

Modul ini tidak mengimpor launcher secara langsung. Ketergantungan ke store
dimuat di dalam fungsi yang membutuhkan database agar urutan impor paket
tetap aman saat launcher mengimpor modul ini.
"""
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

from .paths import DATA_DIR

KERNELS_DIR = DATA_DIR / "kernels"
DEFAULT_KERNEL_FILE = KERNELS_DIR / "default.json"
METADATA_FILE = "kernel.json"
BUILTIN_KERNEL_ID = "builtin"

ELF_MAGIC = b"\x7fELF\x02\x01\x01"
MAX_EXTRACTED_BYTES = int(2.5 * 1024 * 1024 * 1024)
NAME_MAX = 60
ARCHIVE_SUFFIXES = (".tar.xz", ".tar.gz", ".tar.bz2", ".tgz", ".zip")
EXECUTABLE_NAMES = (
    "chrome",
    "chrome-wrapper",
    "chrome_crashpad_handler",
    "chromedriver",
    "chrome_sandbox",
)
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)\.(\d+)")

_size_cache = {}
_install_lock = threading.Lock()


class KernelError(Exception):
    def __init__(self, message, code=1300):
        super().__init__(message)
        self.code = code


def _resolved(path):
    try:
        return str(Path(path).resolve())
    except (OSError, ValueError):
        return str(path)


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _safe_parts(relative):
    """Pecah jalur arsip, tolak segmen yang bisa keluar dari staging."""
    parts = []
    for part in str(relative).replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." or part.endswith(":"):
            return None
        parts.append(part)
    return parts or None


def _member_parts(name):
    """Validasi nama entri arsip sekaligus mengembalikan segmen aman."""
    text = str(name or "").replace("\\", "/")
    if not text or text.startswith("/"):
        return None
    return _safe_parts(text)


def parse_major_version(version):
    """Ambil nomor versi mayor dari keluaran chrome --version."""
    text = str(version or "")
    match = VERSION_PATTERN.search(text)
    if match:
        return int(match.group(1))
    for token in text.replace(".", " ").split():
        if token.isdigit():
            return int(token)
    return 0


def validate_binary_elf(binary_path):
    """True kalau berkas berawalan header ELF Linux 64-bit little-endian."""
    try:
        with open(binary_path, "rb") as handle:
            header = handle.read(len(ELF_MAGIC))
    except OSError:
        return False
    return header == ELF_MAGIC


def calculate_dir_size_mb(path):
    """Total ukuran berkas di dalam direktori, satu desimal, tanpa ikut symlink."""
    root = Path(path)
    if not root.is_dir():
        return 0.0
    total = 0
    for current, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            candidate = Path(current) / name
            try:
                if candidate.is_symlink():
                    continue
                total += candidate.stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def cached_dir_size_mb(path):
    key = _resolved(path)
    if key not in _size_cache:
        _size_cache[key] = calculate_dir_size_mb(path)
    return _size_cache[key]


def invalidate_size_cache(path=None):
    if path is None:
        _size_cache.clear()
        return
    prefix = _resolved(path)
    for key in list(_size_cache):
        if key == prefix or key.startswith(prefix + os.sep):
            _size_cache.pop(key, None)


def read_metadata(folder):
    """Baca kernel.json dari folder kernel, atau None bila tidak ada."""
    path = Path(folder) / METADATA_FILE
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_metadata(folder, metadata):
    target = Path(folder) / METADATA_FILE
    target.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


def folder_created_at(folder):
    metadata = read_metadata(folder)
    if metadata and metadata.get("created_at"):
        return str(metadata["created_at"])
    try:
        stamp = Path(folder).stat().st_mtime
    except OSError:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp))


def _normalize_kernel_id(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text in (".", "..") or "/" in text or "\\" in text:
        return ""
    if Path(text).name != text:
        return ""
    return text


def _read_default_raw():
    try:
        raw = json.loads(DEFAULT_KERNEL_FILE.read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    return _normalize_kernel_id(raw.get("kernel_id"))


def get_default_kernel_id():
    """ID kernel default untuk profil baru, "builtin" bila tidak valid."""
    kernel_id = _read_default_raw()
    if not kernel_id or kernel_id == BUILTIN_KERNEL_ID:
        return BUILTIN_KERNEL_ID
    binary = KERNELS_DIR / kernel_id / "chrome"
    if not _inside(binary, KERNELS_DIR) or not binary.is_file():
        return BUILTIN_KERNEL_ID
    return kernel_id


def set_default_kernel_id(kernel_id):
    clean = _normalize_kernel_id(kernel_id)
    if not clean:
        raise KernelError("kernel_id wajib diisi", 1000)
    if clean != BUILTIN_KERNEL_ID:
        binary = KERNELS_DIR / clean / "chrome"
        if not _inside(binary, KERNELS_DIR) or not binary.is_file():
            raise KernelError("kernel tidak tersedia", 1000)
    KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = DEFAULT_KERNEL_FILE.with_name(DEFAULT_KERNEL_FILE.name + ".tmp")
    temporary.write_text(json.dumps({"kernel_id": clean}) + "\n")
    os.replace(temporary, DEFAULT_KERNEL_FILE)
    return clean


def _profile_preferences():
    from . import store

    try:
        with store.db() as conn:
            rows = conn.execute(
                "SELECT preference_config FROM profiles WHERE deleted_at IS NULL"
            ).fetchall()
    except Exception:
        return []
    return [store._loads(row["preference_config"]) for row in rows]


def _profile_kernel_path(preferences):
    if not isinstance(preferences, dict):
        return ""
    return str(preferences.get("kernel_path") or "").strip()


def profile_counts(builtin_binary, kernel_binaries=()):
    """Jumlah profil aktif per biner kernel, kunci berupa path hasil resolve."""
    builtin_key = _resolved(builtin_binary)
    counts = {builtin_key: 0}
    for binary in kernel_binaries:
        counts[_resolved(binary)] = 0
    for preferences in _profile_preferences():
        raw = _profile_kernel_path(preferences)
        key = _resolved(raw) if raw else builtin_key
        if key not in counts:
            key = builtin_key
        counts[key] += 1
    return counts


def count_profiles_using(binary):
    target = _resolved(binary)
    total = 0
    for preferences in _profile_preferences():
        raw = _profile_kernel_path(preferences)
        if raw and _resolved(raw) == target:
            total += 1
    return total


def _safe_slug(name):
    text = str(name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9.-]+", "-", text)
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    return slug[:NAME_MAX].strip("-.")


def _choose_kernel_id(base, version):
    kernel_id = base or f"chromium-{parse_major_version(version) or 'kernel'}"
    if kernel_id == BUILTIN_KERNEL_ID:
        raise KernelError('nama kernel "builtin" tidak boleh dipakai', 1300)
    candidate = kernel_id
    index = 2
    while True:
        folder = KERNELS_DIR / candidate
        if not folder.exists():
            return candidate
        metadata = read_metadata(folder) or {}
        existing = str(metadata.get("version") or "").strip()
        if (
            version
            and existing == version
            and not count_profiles_using(folder / "chrome")
        ):
            return candidate
        candidate = f"{kernel_id}-{index}"
        index += 1


def _copy_stream(source, target):
    with source, open(target, "wb") as handle:
        shutil.copyfileobj(source, handle)


def _link_symlink(link_name, target, staging):
    link = Path(str(link_name).replace("\\", "/"))
    resolved = (target.parent / link).resolve() if not link.is_absolute() else link.resolve()
    if not _inside(resolved, staging):
        raise KernelError(f"tautan arsip keluar dari direktori kernel: {target.name}", 1300)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    os.symlink(os.path.relpath(resolved, target.parent), target)


def _extract_tar(archive_path, destination):
    try:
        archive = tarfile.open(archive_path, "r:*")
    except (OSError, tarfile.TarError) as error:
        raise KernelError(f"arsip tidak bisa dibuka: {error}", 1300)
    total = 0
    links = []
    with archive:
        for member in archive.getmembers():
            parts = _member_parts(member.name)
            if parts is None:
                raise KernelError(f"entri arsip tidak aman: {member.name}", 1300)
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                raise KernelError(f"entri perangkat tidak diizinkan: {member.name}", 1300)
            if member.issym():
                _link_symlink(member.linkname, target, destination)
                continue
            if member.islnk():
                links.append((member, target))
                continue
            if not member.isfile():
                continue
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise KernelError("ukuran hasil ekstraksi melebihi batas 2.5 GB", 1300)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise KernelError(f"entri arsip tidak bisa dibaca: {member.name}", 1300)
            _copy_stream(source, target)
            _apply_mode(target, member.mode)
    for member, target in links:
        parts = _member_parts(member.linkname)
        if parts is None:
            raise KernelError(f"tautan arsip tidak aman: {member.linkname}", 1300)
        source = destination.joinpath(*parts)
        if not _inside(source, destination) or not source.is_file():
            raise KernelError(f"tautan arsip tidak ditemukan: {member.linkname}", 1300)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        os.link(source, target)


def _zip_member_mode(info):
    return (info.external_attr >> 16) & 0xFFFF


def _extract_zip(archive_path, destination):
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise KernelError(f"arsip tidak bisa dibuka: {error}", 1300)
    total = 0
    with archive:
        for info in archive.infolist():
            parts = _member_parts(info.filename)
            if parts is None:
                raise KernelError(f"entri arsip tidak aman: {info.filename}", 1300)
            target = destination.joinpath(*parts)
            if info.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.mkdir(parents=True, exist_ok=True)
                continue
            mode = _zip_member_mode(info)
            if stat.S_ISLNK(mode):
                raw = archive.read(info).decode("utf-8", "replace").strip()
                _link_symlink(raw, target, destination)
                continue
            total += info.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise KernelError("ukuran hasil ekstraksi melebihi batas 2.5 GB", 1300)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:
                _copy_stream(source, target)
            if mode:
                _apply_mode(target, mode)


def _apply_mode(target, mode):
    try:
        target.chmod(stat.S_IMODE(mode) or 0o644)
    except OSError:
        pass


def _extract_archive(archive_path, destination):
    text = str(archive_path).lower()
    if not text.endswith(ARCHIVE_SUFFIXES):
        raise KernelError(
            "format arsip tidak didukung, gunakan .tar.xz, .tar.gz, .tar.bz2, atau .zip",
            1300,
        )
    if text.endswith(".zip"):
        _extract_zip(archive_path, destination)
    else:
        _extract_tar(archive_path, destination)


def _copy_symlink(source_link, target, root):
    link_target = os.readlink(source_link)
    resolved = (Path(source_link).parent / link_target).resolve()
    if not _inside(resolved, root):
        raise KernelError(f"tautan keluar dari direktori sumber: {source_link}", 1300)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    os.symlink(os.path.relpath(resolved, target.parent), target)


def _copy_tree(source, destination):
    root = Path(source)
    total = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(root)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in list(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                _copy_symlink(candidate, destination / candidate.relative_to(root), root)
                dirs.remove(name)
        for name in files:
            candidate = current_path / name
            target = target_dir / name
            if candidate.is_symlink():
                _copy_symlink(candidate, target, root)
                continue
            if not candidate.is_file():
                continue
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
            if total > MAX_EXTRACTED_BYTES:
                raise KernelError("ukuran hasil salin melebihi batas 2.5 GB", 1300)
            shutil.copy2(candidate, target, follow_symlinks=False)


def _is_usable_chrome(path, root):
    candidate = Path(path)
    try:
        resolved = candidate.resolve()
        resolved.relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _find_chrome(root):
    candidates = []
    for current, _dirs, files in os.walk(root, followlinks=False):
        if "chrome" not in files:
            continue
        candidate = Path(current) / "chrome"
        if _is_usable_chrome(candidate, root):
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (len(item.relative_to(root).parts), str(item)))
    return candidates[0]


def _normalize_layout(work, payload_root):
    """Pindahkan isi induk biner chrome ke satu akar agar chrome ada di akar."""
    chrome = _find_chrome(payload_root)
    if chrome is None:
        raise KernelError("biner chrome tidak ditemukan di dalam sumber", 1301)
    source_root = chrome.parent
    if source_root.resolve() == Path(payload_root).resolve():
        return payload_root
    target = work / "root"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for child in source_root.iterdir():
        shutil.move(str(child), str(target / child.name))
    return target


def _valid_chrome_binary(chrome):
    if validate_binary_elf(chrome):
        return True
    try:
        with open(chrome, "rb") as handle:
            head = handle.read(2)
    except OSError:
        return False
    if head != b"#!":
        return False
    for name in ("chrome-bin", "chromium-bin"):
        if validate_binary_elf(Path(chrome).parent / name):
            return True
    return False


def _read_version(binary):
    try:
        done = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KernelError(
            f"biner chrome gagal dijalankan untuk pembacaan versi: {error}", 1302
        )
    for stream in (done.stdout, done.stderr):
        for line in (stream or "").splitlines():
            line = line.strip()
            if line:
                return line
    raise KernelError("biner chrome gagal dijalankan untuk pembacaan versi", 1302)


def _chmod_executables(root):
    for name in EXECUTABLE_NAMES:
        candidate = Path(root) / name
        try:
            if candidate.exists():
                candidate.chmod(0o755)
        except OSError:
            continue


def _validate_source(path):
    if not str(path or "").strip():
        raise KernelError("path sumber wajib diisi", 1000)
    candidate = Path(str(path)).expanduser()
    try:
        candidate = candidate.resolve()
    except (OSError, ValueError):
        raise KernelError("path sumber tidak valid", 1300)
    if not candidate.exists():
        raise KernelError(f"sumber tidak ditemukan: {candidate}", 1300)
    if _inside(candidate, DATA_DIR / "profiles"):
        raise KernelError("sumber tidak boleh berada di direktori profil", 1300)
    return candidate


def _publish(root, kernel_name, source_label):
    chrome = Path(root) / "chrome"
    if not chrome.is_file() or not _valid_chrome_binary(chrome):
        raise KernelError("biner chrome bukan ELF Linux 64-bit", 1301)
    _chmod_executables(root)
    version = _read_version(chrome)
    major_version = parse_major_version(version)
    name = str(kernel_name or "").strip() or f"Chromium {major_version or version}"
    if len(name) > NAME_MAX:
        raise KernelError(f"nama kernel maksimal {NAME_MAX} karakter", 1000)
    kernel_id = _choose_kernel_id(_safe_slug(name), version)
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "id": kernel_id,
        "name": name,
        "version": version,
        "major_version": major_version,
        "disk_size_mb": 0.0,
        "created_at": created_at,
        "source": source_label,
    }
    _write_metadata(root, metadata)
    target = KERNELS_DIR / kernel_id
    KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        backup = KERNELS_DIR / f".trash-{os.getpid()}-{secrets.token_hex(4)}"
        shutil.move(str(target), str(backup))
    try:
        shutil.move(str(root), str(target))
    except Exception:
        if backup is not None:
            shutil.move(str(backup), str(target))
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
    metadata["disk_size_mb"] = calculate_dir_size_mb(target)
    _write_metadata(target, metadata)
    invalidate_size_cache(KERNELS_DIR)
    return {
        "id": kernel_id,
        "name": name,
        "version": version,
        "major_version": major_version,
        "path": str(target / "chrome"),
        "disk_size_mb": metadata["disk_size_mb"],
        "created_at": created_at,
    }


def _install(source, kernel_name, extract):
    with _install_lock:
        source_path = _validate_source(source)
        KERNELS_DIR.mkdir(parents=True, exist_ok=True)
        work = KERNELS_DIR / f".install-{os.getpid()}-{secrets.token_hex(4)}"
        work.mkdir(parents=True)
        payload_root = work / "payload"
        payload_root.mkdir()
        try:
            extract(source_path, payload_root)
            root = _normalize_layout(work, payload_root)
            return _publish(root, kernel_name, str(source_path))
        finally:
            shutil.rmtree(work, ignore_errors=True)


def install_kernel_from_archive(archive_path, kernel_name=None):
    """Pasang kernel dari arsip tar/zip dan kembalikan metadata dasarnya."""
    source = _validate_source(archive_path)
    if not source.is_file():
        raise KernelError("sumber arsip harus berupa berkas", 1300)
    return _install(source, kernel_name, _extract_archive)


def install_kernel_from_dir(source_dir, kernel_name=None):
    """Pasang kernel dari folder lokal yang sudah diekstrak."""
    source = _validate_source(source_dir)
    if not source.is_dir():
        raise KernelError("sumber harus berupa folder", 1300)
    if _inside(KERNELS_DIR, source):
        raise KernelError("sumber tidak boleh memuat direktori kernel", 1300)
    return _install(source, kernel_name, _copy_tree)


def delete_kernel(kernel_id):
    """Hapus kernel tambahan, tolak builtin dan kernel yang masih dipakai."""
    clean = _normalize_kernel_id(kernel_id)
    if not clean:
        raise KernelError("kernel_id wajib diisi", 1000)
    if clean == BUILTIN_KERNEL_ID:
        raise KernelError("Engine bawaan tidak bisa dihapus", 1104)
    folder = KERNELS_DIR / clean
    if clean.startswith(".") or not folder.is_dir() or not _inside(folder, KERNELS_DIR):
        raise KernelError("Kernel tidak ditemukan", 1103)
    binary = folder / "chrome"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise KernelError("Kernel tidak ditemukan", 1103)
    used = count_profiles_using(binary)
    if used:
        raise KernelError(
            f"Kernel masih digunakan oleh {used} profil aktif, "
            "ubah kernel profil tersebut terlebih dahulu",
            1105,
        )
    was_default = _read_default_raw() == clean
    shutil.rmtree(folder)
    invalidate_size_cache(folder)
    invalidate_size_cache(KERNELS_DIR)
    if was_default:
        set_default_kernel_id(BUILTIN_KERNEL_ID)
    return {
        "deleted": True,
        "kernel_id": clean,
        "default_kernel_id": get_default_kernel_id(),
    }
