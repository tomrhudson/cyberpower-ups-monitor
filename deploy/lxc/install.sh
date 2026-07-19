#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run this installer as root inside the target LXC" >&2
  exit 1
fi

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
APP_ROOT=/opt/cyberpower-ups-monitor
CONFIG_ROOT=/etc/cyberpower-ups-monitor
DATA_ROOT=/var/lib/cyberpower-ups-monitor

apt-get update
apt-get install -y --no-install-recommends python3 ca-certificates

if ! id ups-monitor >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_ROOT" --shell /usr/sbin/nologin ups-monitor
fi

install -d -m 0755 "$APP_ROOT" "$CONFIG_ROOT"
install -d -o ups-monitor -g ups-monitor -m 0750 "$DATA_ROOT"
rm -rf "$APP_ROOT/src"
cp -R "$REPO_ROOT/src" "$APP_ROOT/src"
cp "$REPO_ROOT/pyproject.toml" "$APP_ROOT/pyproject.toml"
cp "$REPO_ROOT/README.md" "$APP_ROOT/README.md"

if [ ! -f "$CONFIG_ROOT/devices.json" ]; then
  install -m 0644 "$REPO_ROOT/config/devices.example.json" "$CONFIG_ROOT/devices.json"
fi
if [ ! -f "$CONFIG_ROOT/monitor.env" ]; then
  install -m 0640 "$REPO_ROOT/deploy/systemd/monitor.env.example" "$CONFIG_ROOT/monitor.env"
fi
if [ ! -f "$CONFIG_ROOT/ingest-token" ]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$CONFIG_ROOT/ingest-token"
fi
chown root:ups-monitor "$CONFIG_ROOT/monitor.env" "$CONFIG_ROOT/ingest-token"
chmod 0640 "$CONFIG_ROOT/monitor.env" "$CONFIG_ROOT/ingest-token"

install -m 0644 \
  "$REPO_ROOT/deploy/systemd/cyberpower-ups-monitor.service" \
  /etc/systemd/system/cyberpower-ups-monitor.service
systemctl daemon-reload
systemctl enable --now cyberpower-ups-monitor.service

echo "CyberPower UPS Monitor installed on port 8787."
