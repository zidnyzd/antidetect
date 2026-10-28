#!/usr/bin/env python3
"""Wrapper wajib untuk menjalankan engine antidetect.

Mesin ini sudah dua kali crash karena probe membuka ribuan Chrome paralel.
Dokumen tidak cukup untuk mencegah itu, jadi setiap peluncuran engine harus
lewat berkas ini. Wrapper menegakkan:

1. Batas instance hidup: maksimal 6 engine antidetect sekaligus, dihitung
   gabungan untuk seluruh kernel di ENGINE_DIR dan KERNELS_DIR.
2. Batas laju peluncuran: maksimal 20 peluncuran per menit.
3. Lokasi user-data-dir: hanya di ~/.local/share/antidetect/profiles atau
   /dev/shm/antidetect, supaya probe tidak menumpuk folder data di disk root.
4. Validasi biner --engine: path hasil realpath wajib berada di bawah
   ENGINE_DIR atau KERNELS_DIR dan bernama chrome.
5. Pendaftaran intent ke penjaga lewat /tmp/antidetect-engine-control.

Pemakaian:
    antidetect-engine-wrapper.py --engine /path/chrome -- <argumen chrome>
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

CONTROL = Path("/tmp/antidetect-engine-control")
MAX_INSTANCES = 6
MAX_LAUNCHES_PER_MINUTE = 20
WINDOW_SECONDS = 60


def allowed_data_prefixes():
    data_dir = Path(
        os.environ.get("ANTIDETECT_HOME")
        or Path.home() / ".local" / "share" / "antidetect"
    )
    return (str(data_dir / "profiles"), "/dev/shm/antidetect")


def engine_dirs():
    """Direktori engine bawaan dan koleksi kernel tambahan."""
    data_dir = Path(
        os.environ.get("ANTIDETECT_HOME")
        or Path.home() / ".local" / "share" / "antidetect"
    )
    engine_dir = Path(
        os.environ.get("ANTIDETECT_ENGINE_DIR")
        or data_dir / "squashfs-root" / "opt" / "ungoogled-chromium"
    )
    return engine_dir, data_dir / "kernels"


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def validate_engine_binary(engine_path):
    """Kembalikan realpath biner engine yang sah, atau None."""
    if not engine_path:
        return None
    try:
        real = os.path.realpath(engine_path)
    except OSError:
        return None
    engine_dir, kernels_dir = engine_dirs()
    if not any(_inside(real, root) for root in (engine_dir, kernels_dir)):
        return None
    if os.path.basename(real) != "chrome":
        return None
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        return None
    return real


def _managed_binary(path):
    engine_dir, kernels_dir = engine_dirs()
    return any(_inside(path, root) for root in (engine_dir, kernels_dir))


def read_intents():
    try:
        raw = CONTROL.read_text()
    except OSError:
        return 0.0, 0
    try:
        first_ts, count = raw.strip().split("|")
        return float(first_ts), int(count)
    except ValueError:
        return 0.0, 0


def register_intent():
    """Catat satu peluncuran ke control file."""
    first_ts, count = read_intents()
    now = time.time()
    if now - first_ts > WINDOW_SECONDS:
        first_ts, count = now, 0
    count += 1
    try:
        CONTROL.parent.mkdir(parents=True, exist_ok=True)
        CONTROL.write_text(f"{first_ts}|{count}")
    except OSError:
        pass
    return first_ts, count


def count_live_instances():
    """Jumlah jendela engine hidup, gabungan semua kernel.

    Satu jendela browser memiliki satu --user-data-dir. Proses renderer
    memakai direktori yang sama, jadi instance dihitung per direktori data,
    bukan per proses. Semua biner di bawah ENGINE_DIR dan KERNELS_DIR ikut
    dihitung agar batas MAX_INSTANCES tidak bisa ditembus dengan berpindah
    kernel.
    """
    data_dirs = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        if not _managed_binary(exe):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        parts = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
        for index, arg in enumerate(parts):
            if arg.startswith("--user-data-dir="):
                data_dirs.add(os.path.abspath(arg.split("=", 1)[1]))
                break
            if arg == "--user-data-dir" and index + 1 < len(parts):
                data_dirs.add(os.path.abspath(parts[index + 1]))
                break
    return len(data_dirs)


def data_dir_of(argv):
    for index, arg in enumerate(argv):
        if arg.startswith("--user-data-dir="):
            return arg.split("=", 1)[1]
        if arg == "--user-data-dir" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def fail(message):
    print(f"engine guard: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    engine = None
    if argv and argv[0] == "--engine":
        if len(argv) < 2:
            fail("--engine butuh path")
        engine = argv[1]
        argv = argv[2:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not engine:
        fail("pakai --engine <path>")

    engine = validate_engine_binary(engine)
    if not engine:
        fail("path engine di luar lokasi yang diizinkan")

    if "--version" in argv or "--help" in argv:
        os.execv(engine, [engine] + argv)
        return

    data_dir = data_dir_of(argv)
    if not data_dir:
        fail("--user-data-dir wajib untuk engine")
    data_dir = os.path.abspath(os.path.expanduser(data_dir))
    if not any(data_dir.startswith(prefix) for prefix in allowed_data_prefixes()):
        fail(
            "user-data-dir di luar lokasi yang diizinkan: "
            f"{data_dir}. Gunakan ~/.local/share/antidetect/profiles/... "
            "atau /dev/shm/antidetect/..."
        )

    live = count_live_instances()
    if live >= MAX_INSTANCES:
        fail(f"instance engine yang hidup sudah {live}, batas {MAX_INSTANCES}")

    first_ts, count = register_intent()
    if time.time() - first_ts > WINDOW_SECONDS:
        first_ts, count = time.time(), 1
    if count > MAX_LAUNCHES_PER_MINUTE:
        fail(f"laju peluncuran {count}/{WINDOW_SECONDS}s, batas {MAX_LAUNCHES_PER_MINUTE}")

    process = subprocess.Popen([engine] + argv)

    def relay(signum, frame):
        try:
            process.send_signal(signum)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, relay)
    signal.signal(signal.SIGINT, relay)
    try:
        sys.exit(process.wait())
    except KeyboardInterrupt:
        relay(signal.SIGINT, None)
        sys.exit(130)


if __name__ == "__main__":
    main()
