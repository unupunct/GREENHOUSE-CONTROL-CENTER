#!/usr/bin/env bash
# Install Greenhouse Control Center as a systemd service on Debian-based systems
# (ParrotOS, Debian, Ubuntu, Raspberry Pi OS). Needs root. Re-running it upgrades in place; data is kept.
# NOT yet tested on a Raspberry Pi or ParrotOS machine. Read it before running.
#
# Usage: sudo ./deploy/install.sh [--demo] [--local-only]
#   --demo        seed simulated sensors and equipment on an empty database (to try the program without hardware)
#   --local-only  listen on 127.0.0.1 only (this computer), instead of the whole network
set -euo pipefail

APP_DIR=/opt/greenhouse
ENV_FILE=/etc/greenhouse/greenhouse.env
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO=false
BIND=0.0.0.0
SET_OPTIONS=false
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=true; SET_OPTIONS=true ;;
    --local-only) BIND=127.0.0.1; SET_OPTIONS=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo $0 $*" >&2; exit 1; fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer needs apt (Debian, Ubuntu, ParrotOS, Raspberry Pi OS). On other systems see docs/INSTALLATION.md (manual run)." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then echo "systemd is required (systemctl not found)." >&2; exit 1; fi

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip rsync i2c-tools
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required (found $(python3 --version 2>&1))." >&2
  exit 1
fi
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

echo "==> Settings ($ENV_FILE)"
mkdir -p "$(dirname "$ENV_FILE")"
if [ "$SET_OPTIONS" = true ] || [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# Read by the greenhouse service (systemctl restart greenhouse after editing).
# GCC_SIMULATE only matters on an EMPTY database: true seeds simulated demo devices, false starts a real installation.
GCC_SIMULATE=$DEMO
# 0.0.0.0 = reachable from your network, 127.0.0.1 = this computer only
GCC_BIND_HOST=$BIND
EOF
else
  echo "keeping the existing settings file"
fi

echo "==> systemd service"
install -m 644 "$APP_DIR/deploy/greenhouse.service" /etc/systemd/system/greenhouse.service
systemctl daemon-reload
systemctl enable greenhouse.service
systemctl restart greenhouse.service

HOST_BIND=$(sed -n 's/^GCC_BIND_HOST=//p' "$ENV_FILE" | tail -1)
if [ "$HOST_BIND" = "127.0.0.1" ]; then ADDR=127.0.0.1; else ADDR=$(hostname -I 2>/dev/null | awk '{print $1}'); fi
ADDR=${ADDR:-127.0.0.1}

echo
echo "Done. Status:  systemctl status greenhouse"
echo "Logs:          journalctl -u greenhouse -f"
echo "Open:          http://$ADDR:8000"
echo "First start: open the address above and create the administrator with the one-time code in"
echo "  /var/lib/greenhouse/setup_code.txt   (sudo cat /var/lib/greenhouse/setup_code.txt)"
echo "The interface speaks plain HTTP: keep it on your private network, never forward port 8000 to the internet"
echo "(see docs/SECURITY.md for HTTPS behind a reverse proxy)."
echo "Desktop shortcut (run as your normal user, not root): bash $APP_DIR/deploy/add-desktop-shortcut.sh"
