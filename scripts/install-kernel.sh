#!/usr/bin/env bash
# Pasang kernel Chromium tambahan lewat API lokal, atau langsung lewat modul
# kernels bila server antidetect tidak sedang berjalan.
set -euo pipefail

usage() {
  echo "Pemakaian: $0 <path-arsip-atau-folder> [nama-kernel]" >&2
  echo "Contoh: $0 ~/Downloads/ungoogled-chromium-152-linux.tar.xz \"Chromium 152\"" >&2
  exit 2
}

if [ "$#" -lt 1 ]; then
  usage
fi

SOURCE_INPUT=$1
KERNEL_NAME=${2:-}

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${ANTIDETECT_PYTHON:-$REPO_ROOT/venv/bin/python}
if [ ! -x "$PYTHON" ]; then
  PYTHON=$(command -v python3)
fi

if [ ! -e "$SOURCE_INPUT" ]; then
  echo "Sumber tidak ditemukan: $SOURCE_INPUT" >&2
  exit 1
fi

SOURCE=$(realpath -- "$SOURCE_INPUT")
if [ -d "$SOURCE" ]; then
  SOURCE_TYPE=local_dir
else
  SOURCE_TYPE=local_archive
fi

exec "$PYTHON" - "$SOURCE_TYPE" "$SOURCE" "$KERNEL_NAME" "$REPO_ROOT" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

source_type, source, kernel_name, repo_root = sys.argv[1:5]
payload = {"source_type": source_type, "kernel_name": kernel_name}
payload["source_path" if source_type == "local_dir" else "archive_path"] = source

base = os.environ.get("ANTIDETECT_API_URL", "http://127.0.0.1:53200/api/v2").rstrip("/")
root = base[: -len("/api/v2")] if base.endswith("/api/v2") else base


def api_ready():
    try:
        with urllib.request.urlopen(root + "/health", timeout=2):
            return True
    except (OSError, urllib.error.URLError):
        return False


def post_install():
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        base + "/kernel-install",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


if api_ready():
    body = post_install()
    error = body.get("error") or {}
    if error.get("code"):
        print(error.get("message") or "instalasi gagal", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(body.get("data"), ensure_ascii=False, indent=2))
    raise SystemExit(0)

sys.path.insert(0, repo_root)
from antidetect import kernels

try:
    if source_type == "local_dir":
        result = kernels.install_kernel_from_dir(source, kernel_name or None)
    else:
        result = kernels.install_kernel_from_archive(source, kernel_name or None)
except kernels.KernelError as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)

print(json.dumps(result, ensure_ascii=False, indent=2))
PY
