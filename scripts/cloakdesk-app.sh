#!/bin/bash
# CloakDesk Standalone Desktop App Launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

# 1. Pastikan backend CloakDesk aktif di port 53200
if ! curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
    PY="/usr/bin/python3"
    [ -x "$PYTHON_BIN" ] && PY="$PYTHON_BIN"
    nohup "$PY" -m antidetect serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        if curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

# 2. Prioritaskan runtime Electron mandiri (100% standalone native seperti ixBrowser)
ELECTRON_BIN="$PROJECT_DIR/ui/node_modules/.bin/electron"
MAIN_CJS="$PROJECT_DIR/ui/electron-main.cjs"

if [ -x "$ELECTRON_BIN" ] && [ -f "$MAIN_CJS" ]; then
    exec "$ELECTRON_BIN" "$MAIN_CJS" "$@"
fi

# Fallback ke browser jika Electron belum terpasang
URL="http://127.0.0.1:53200/#/profiles"
exec xdg-open "$URL"
