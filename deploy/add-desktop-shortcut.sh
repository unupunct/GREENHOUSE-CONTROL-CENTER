#!/usr/bin/env bash
# Add a "Greenhouse Control Center" launcher (desktop icon + application menu entry) that opens the web interface.
# Run as your NORMAL user (not root), e.g. on ParrotOS:
#   curl -fsSL https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/deploy/add-desktop-shortcut.sh | bash
# Optional first argument: the address to open (default http://localhost:8000; use http://<pi-address>:8000 for a Pi).
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then echo "Run this as your normal user, not root (the shortcut belongs to your desktop)." >&2; exit 1; fi

URL="${1:-http://localhost:8000}"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$ICON_DIR" "$APP_DIR" "$DESKTOP_DIR"

cat > "$ICON_DIR/greenhouse-control-center.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#14532d"/>
  <path d="M10 50V30L32 12l22 18v20z" fill="none" stroke="#bbf7d0" stroke-width="3" stroke-linejoin="round"/>
  <path d="M32 50V34M32 40c0-6 4-9 9-9 0 6-3 9-9 9zM32 44c0-5-3-8-8-8 0 5 3 8 8 8z" fill="#86efac" stroke="#86efac" stroke-width="2" stroke-linejoin="round"/>
</svg>
SVG

LAUNCHER="$APP_DIR/greenhouse-control-center.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Greenhouse Control Center
Comment=Open the greenhouse monitoring and control interface
Exec=xdg-open $URL
Icon=greenhouse-control-center
Terminal=false
Categories=Utility;
EOF
chmod +x "$LAUNCHER"
cp "$LAUNCHER" "$DESKTOP_DIR/greenhouse-control-center.desktop"
chmod +x "$DESKTOP_DIR/greenhouse-control-center.desktop"
# file managers (Caja, Nautilus, Nemo...) ask before running unknown launchers; mark ours as trusted where supported
gio set "$DESKTOP_DIR/greenhouse-control-center.desktop" metadata::trusted true 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" 2>/dev/null || true

echo "Shortcut added: $DESKTOP_DIR/greenhouse-control-center.desktop (also in the application menu). It opens $URL"
echo "If the desktop asks, choose \"Trust and Launch\" / \"Allow Launching\" once."
