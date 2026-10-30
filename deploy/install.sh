#!/usr/bin/env bash
# Install Greenhouse Control Center as a systemd service on Raspberry Pi OS / Debian.
# NOT yet tested on a Raspberry Pi. Read it before running; it needs sudo.
# Usage: sudo ./deploy/install.sh        (run from the repository root, copied to /opt/greenhouse)
set -euo pipefail

APP_DIR=/opt/greenhouse
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip rsync i2c-tools
# GPIO outputs/inputs use gpiozero; on Raspberry Pi OS it is installed from apt (the venv below can see system packages)
apt-get install -y python3-gpiozero python3-lgpio || echo "note: gpiozero/lgpio not available from apt: GPIO drivers will report an error until installed"

echo "==> Copying application to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude '.venv' --exclude 'node_modules' --exclude 'data' --exclude '__pycache__' \
  "$SRC_DIR/" "$APP_DIR/"

echo "==> Creating service user"
id greenhouse >/dev/null 2>&1 || useradd --system --home /var/lib/greenhouse --shell /usr/sbin/nologin greenhouse
for g in dialout i2c gpio; do getent group "$g" >/dev/null && usermod -aG "$g" greenhouse || true; done

echo "==> Python environment"
python3 -m venv --system-site-packages "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

if [ ! -f "$APP_DIR/frontend/dist/index.html" ]; then
  echo "!! frontend/dist is missing. Build it on another computer (npm install && npm run build in frontend/)"
  echo "   and copy frontend/dist to $APP_DIR/frontend/dist, then restart the service."
fi

echo "==> systemd service"
install -m 644 "$APP_DIR/deploy/greenhouse.service" /etc/systemd/system/greenhouse.service
systemctl daemon-reload
systemctl enable --now greenhouse.service

echo
echo "Done. Status:  systemctl status greenhouse"
echo "Logs:          journalctl -u greenhouse -f"
echo "Open:          http://$(hostname -I | awk '{print $1}'):8000"
echo "First start: open the address above and create the administrator with the one-time code in"
echo "  /var/lib/greenhouse/setup_code.txt   (sudo cat /var/lib/greenhouse/setup_code.txt)"
echo "The interface speaks plain HTTP: keep it on your private network, never forward port 8000 to the internet"
echo "(see docs/SECURITY.md for HTTPS behind a reverse proxy)."
