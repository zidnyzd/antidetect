#!/bin/bash
# Skrip pembangun paket .deb resmi untuk CloakDesk
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="0.2.0"
PKG_NAME="cloakdesk"
ARCH="amd64"
DIST_DIR="$PROJECT_DIR/dist"
STAGING_DIR="$PROJECT_DIR/build/deb_staging"

echo "=== 1. Memeriksa build UI ==="
cd "$PROJECT_DIR/ui"
if [ ! -f "dist/index.html" ]; then
    echo "Membangun frontend ui/dist..."
    npm run build
fi

echo "=== 2. Menyiapkan direktori paket ==="
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/DEBIAN"
mkdir -p "$STAGING_DIR/opt/cloakdesk/antidetect"
mkdir -p "$STAGING_DIR/opt/cloakdesk/ui/dist"
mkdir -p "$STAGING_DIR/opt/cloakdesk/assets"
mkdir -p "$STAGING_DIR/opt/cloakdesk/scripts"
mkdir -p "$STAGING_DIR/usr/bin"
mkdir -p "$STAGING_DIR/usr/share/applications"
mkdir -p "$STAGING_DIR/usr/share/icons/hicolor/512x512/apps"
mkdir -p "$STAGING_DIR/usr/share/icons/hicolor/scalable/apps"

echo "=== 3. Menyalin berkas aplikasi ==="
cp -a "$PROJECT_DIR/antidetect/"* "$STAGING_DIR/opt/cloakdesk/antidetect/"
find "$STAGING_DIR/opt/cloakdesk/antidetect" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
cp -a "$PROJECT_DIR/ui/dist/"* "$STAGING_DIR/opt/cloakdesk/ui/dist/"
cp "$PROJECT_DIR/assets/cloakdesk-logo.png" "$STAGING_DIR/opt/cloakdesk/assets/"
cp "$PROJECT_DIR/assets/cloakdesk-logo.svg" "$STAGING_DIR/opt/cloakdesk/assets/"
cp "$PROJECT_DIR/scripts/fetch-gost.sh" "$STAGING_DIR/opt/cloakdesk/scripts/" 2>/dev/null || true

# Ikon sistem
cp "$PROJECT_DIR/assets/cloakdesk-logo.png" "$STAGING_DIR/usr/share/icons/hicolor/512x512/apps/cloakdesk.png"
cp "$PROJECT_DIR/assets/cloakdesk-logo.svg" "$STAGING_DIR/usr/share/icons/hicolor/scalable/apps/cloakdesk.svg"

# Desktop Entry
cat <<'EOF' > "$STAGING_DIR/usr/share/applications/cloakdesk.desktop"
[Desktop Entry]
Version=1.0
Terminal=false
Type=Application
Name=CloakDesk
Comment=Antidetect Browser Profile Manager
Exec=/usr/bin/cloakdesk
Icon=cloakdesk
Categories=Network;WebBrowser;GTK;
StartupWMClass=CloakDesk
StartupNotify=true
Actions=NewWindow;

[Desktop Action NewWindow]
Name=Buka CloakDesk
Exec=/usr/bin/cloakdesk
EOF

# Executable /usr/bin/cloakdesk
cat <<'EOF' > "$STAGING_DIR/usr/bin/cloakdesk"
#!/bin/bash
set -e

# CloakDesk CLI & Desktop Launcher
CLOAKDESK_DIR="/opt/cloakdesk"
export PYTHONPATH="$CLOAKDESK_DIR:$PYTHONPATH"

# Jika dipanggil dengan argumen subperintah CLI (misal: cloakdesk serve, cloakdesk list)
if [ "$#" -gt 0 ]; then
    exec /usr/bin/python3 -m antidetect "$@"
fi

# Jika dipanggil tanpa argumen: mode Desktop GUI
# 1. Pastikan backend server aktif
if ! curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
    nohup /usr/bin/python3 -m antidetect serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        if curl -s -m 1 http://127.0.0.1:53200/health >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

# 2. Cari runtime browser untuk jendela aplikasi mandiri
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
    exec xdg-open "$URL"
fi
EOF
chmod 755 "$STAGING_DIR/usr/bin/cloakdesk"

# Berkas kontrol paket Debian
cat <<EOF > "$STAGING_DIR/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), curl
Recommends: brave-browser | chromium-browser | google-chrome-stable | firefox
Maintainer: zidnyzd <https://github.com/zidnyzd/cloakdesk>
Homepage: https://github.com/zidnyzd/cloakdesk
Description: Local-first antidetect browser profile manager for Linux.
 CloakDesk provides an ixBrowser Local API v2 compatible local daemon
 and modern desktop interface with multi-device encrypted synchronization
 on top of fingerprint-chromium.
EOF

# Post-installation script (update desktop database)
cat <<'EOF' > "$STAGING_DIR/DEBIAN/postinst"
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    if which update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if which gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi
exit 0
EOF
chmod 755 "$STAGING_DIR/DEBIAN/postinst"

# Post-removal script
cat <<'EOF' > "$STAGING_DIR/DEBIAN/postrm"
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if which update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if which gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi
exit 0
EOF
chmod 755 "$STAGING_DIR/DEBIAN/postrm"

echo "=== 4. Membangun paket .deb ==="
mkdir -p "$DIST_DIR"
DEB_FILE="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGING_DIR" "$DEB_FILE"

echo "=== Selesai! Paket berhasil dibuat: $DEB_FILE ==="
dpkg-deb -I "$DEB_FILE"
