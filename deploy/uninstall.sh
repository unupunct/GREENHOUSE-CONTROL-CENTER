#!/usr/bin/env bash
# Remove the Greenhouse Control Center service and program files.
# Your data (/var/lib/greenhouse: database, backups) is KEPT unless you pass --purge-data.
# Usage: sudo /opt/greenhouse/deploy/uninstall.sh [--purge-data]
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo $0 $*" >&2; exit 1; fi

systemctl disable --now greenhouse.service 2>/dev/null || true
rm -f /etc/systemd/system/greenhouse.service
systemctl daemon-reload
rm -rf /opt/greenhouse /etc/greenhouse
if [ "${1:-}" = "--purge-data" ]; then
  rm -rf /var/lib/greenhouse
  userdel greenhouse 2>/dev/null || true
  echo "Removed the program AND all data."
else
  echo "Removed the program. Data kept in /var/lib/greenhouse (delete it yourself, or re-run with --purge-data)."
fi
