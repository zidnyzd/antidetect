#!/bin/bash
# CloakDesk Standalone Desktop App Launcher
set -e

# Cari direktori root CloakDesk yang valid
if [ -f "/home/zdna/Projects/cloakdesk/ui/electron-main.cjs" ]; then
    PROJECT_DIR="/home/zdna/Projects/cloakdesk"
elif [ -f "/opt/cloakdesk/ui/electron-main.cjs" ]; then
    PROJECT_DIR="/opt/cloakdesk"
else
    SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
    PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

# 0. Jika dipanggil dengan argumen subperintah CLI (misal: cloakdesk sync, cloakdesk list)
if [ "$#" -gt 0 ]; then
    PY="/usr/bin/python3"
    [ -x "$PYTHON_BIN" ] && PY="$PYTHON_BIN"
    export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"
    exec "$PY" -m antidetect "$@"
fi

# 1. Pastikan backend CloakDesk aktif di port 53200
if ! curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
    PY="/usr/bin/python3"
    [ -x "$PYTHON_BIN" ] && PY="$PYTHON_BIN"
    export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"
    nohup "$PY" -m antidetect serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        if curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

# 2. Prioritaskan runtime Electron mandiri (100% standalone native seperti ixBrowser)
ELECTRON_BIN=""
if [ -x "$PROJECT_DIR/ui/node_modules/.bin/electron" ]; then
    ELECTRON_BIN="$PROJECT_DIR/ui/node_modules/.bin/electron"
elif [ -x "/home/zdna/Projects/cloakdesk/ui/node_modules/.bin/electron" ]; then
    ELECTRON_BIN="/home/zdna/Projects/cloakdesk/ui/node_modules/.bin/electron"
elif command -v electron >/dev/null 2>&1; then
    ELECTRON_BIN="$(command -v electron)"
fi

MAIN_CJS="$PROJECT_DIR/ui/electron-main.cjs"
if [ ! -f "$MAIN_CJS" ] && [ -f "/home/zdna/Projects/cloakdesk/ui/electron-main.cjs" ]; then
    MAIN_CJS="/home/zdna/Projects/cloakdesk/ui/electron-main.cjs"
fi

if [ -n "$ELECTRON_BIN" ] && [ -f "$MAIN_CJS" ]; then
    exec "$ELECTRON_BIN" "$MAIN_CJS" "$@"
fi

# Fallback ke browser jika Electron belum terpasang
URL="http://127.0.0.1:53200/#/profiles"
exec xdg-open "$URL"
