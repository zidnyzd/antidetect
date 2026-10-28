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
cp "$PROJECT_DIR/ui/electron-main.cjs" "$STAGING_DIR/opt/cloakdesk/ui/"
cp "$PROJECT_DIR/assets/cloakdesk-logo.png" "$STAGING_DIR/opt/cloakdesk/assets/"
cp "$PROJECT_DIR/assets/cloakdesk-logo.svg" "$STAGING_DIR/opt/cloakdesk/assets/"
cp "$PROJECT_DIR/scripts/fetch-gost.sh" "$STAGING_DIR/opt/cloakdesk/scripts/" 2>/dev/null || true
cp "$PROJECT_DIR/scripts/cloakdesk-app.sh" "$STAGING_DIR/opt/cloakdesk/scripts/"

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
cp "$PROJECT_DIR/scripts/cloakdesk-app.sh" "$STAGING_DIR/usr/bin/cloakdesk"
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
