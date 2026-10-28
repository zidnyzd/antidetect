#!/bin/bash
# CloakDesk Standalone Desktop App Launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

# 1. Pastikan backend CloakDesk aktif di port 53200
if ! curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
    nohup "$PYTHON_BIN" -m antidetect serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        if curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

# 2. Cari runtime browser untuk jendela aplikasi mandiri (app mode)
APP_BROWSER=""
if [ -x "/opt/brave.com/brave-origin/brave" ]; then
    APP_BROWSER="/opt/brave.com/brave-origin/brave"
elif command -v brave-browser >/dev/null 2>&1; then
    APP_BROWSER="$(command -v brave-browser)"
elif command -v google-chrome >/dev/null 2>&1; then
    APP_BROWSER="$(command -v google-chrome)"
elif command -v chromium-browser >/dev/null 2>&1; then
    APP_BROWSER="$(command -v chromium-browser)"
elif command -v chromium >/dev/null 2>&1; then
    APP_BROWSER="$(command -v chromium)"
fi

URL="http://127.0.0.1:53200/#/profiles"
USER_DATA="$HOME/.config/cloakdesk/app-shell"
mkdir -p "$USER_DATA"

if [ -n "$APP_BROWSER" ]; then
    exec "$APP_BROWSER" \
        --app="$URL" \
        --class="CloakDesk" \
        --name="CloakDesk" \
        --user-data-dir="$USER_DATA" \
        --window-size=1280,820 \
        "$@"
else
    # Fallback ke browser default sistem
    exec xdg-open "$URL"
fi
