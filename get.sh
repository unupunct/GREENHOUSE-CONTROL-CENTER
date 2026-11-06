#!/usr/bin/env bash
# One-line installer for ParrotOS, Debian, Ubuntu and Raspberry Pi OS:
#   curl -fsSL https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/get.sh | sudo bash
# Options (after "bash -s --"): --demo (simulated devices to try it), --local-only (this computer only).
# It downloads the release archive from GitHub and runs deploy/install.sh from it. Read both before running.
# Environment: GCC_VERSION (release to install), GCC_ARCHIVE (a local .tar.gz instead of downloading).
set -euo pipefail

REPO=unupunct/GREENHOUSE-CONTROL-CENTER
VERSION="${GCC_VERSION:-0.9.1}"
URL="https://github.com/$REPO/releases/download/v$VERSION/greenhouse-control-center-$VERSION.tar.gz"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: curl -fsSL https://raw.githubusercontent.com/$REPO/main/get.sh | sudo bash" >&2
  exit 1
fi
command -v apt-get >/dev/null 2>&1 || { echo "apt-get not found: this installer is for Debian-based systems (ParrotOS, Debian, Ubuntu, Raspberry Pi OS)." >&2; exit 1; }

# curl and tar are tiny and present on virtually every system, but make sure
for tool in curl tar; do
  command -v "$tool" >/dev/null 2>&1 || { apt-get update && apt-get install -y "$tool"; }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "${GCC_ARCHIVE:-}" ]; then
  echo "==> Using local archive $GCC_ARCHIVE"
  cp "$GCC_ARCHIVE" "$TMP/gcc.tar.gz"
else
  echo "==> Downloading Greenhouse Control Center $VERSION"
  curl -fL --retry 3 -o "$TMP/gcc.tar.gz" "$URL"
fi
tar -xzf "$TMP/gcc.tar.gz" -C "$TMP"
DIR="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -f "$DIR/deploy/install.sh" ] || { echo "The archive does not look right (deploy/install.sh missing)." >&2; exit 1; }

bash "$DIR/deploy/install.sh" "$@"
