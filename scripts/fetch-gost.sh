#!/usr/bin/env bash
# Idempotent installer for the gost proxy bridge (https://github.com/go-gost/gost).
set -euo pipefail

DEST_DIR="${HOME}/.local/bin"
DEST="${DEST_DIR}/gost"

if [ -x "${DEST}" ] && "${DEST}" -V >/dev/null 2>&1; then
    echo "gost sudah terpasang: $("${DEST}" -V)"
    exit 0
fi

if ! command -v gh >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
    echo "butuh gh atau curl untuk mengunduh gost" >&2
    exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

if command -v gh >/dev/null 2>&1; then
    gh release download -R go-gost/gost -p '*linux_amd64.tar.gz' -D "${TMP}" --clobber
else
    ASSET="$(curl -fsSL https://api.github.com/repos/go-gost/gost/releases/latest \
        | grep -o '"browser_download_url": *"[^"]*linux_amd64\.tar\.gz"' \
        | head -n1 | cut -d'"' -f4)"
    [ -n "${ASSET}" ] || { echo "asset linux_amd64 tidak ditemukan" >&2; exit 1; }
    curl -fsSL "${ASSET}" -o "${TMP}/gost_linux_amd64.tar.gz"
fi

ARCHIVE="$(find "${TMP}" -maxdepth 1 -name '*linux_amd64.tar.gz' | head -n1)"
[ -n "${ARCHIVE}" ] || { echo "arsip gost tidak ditemukan" >&2; exit 1; }
tar -xzf "${ARCHIVE}" -C "${TMP}"

mkdir -p "${DEST_DIR}"
install -m 0755 "${TMP}/gost" "${DEST}"
"${DEST}" -V
echo "gost terpasang di ${DEST}"
