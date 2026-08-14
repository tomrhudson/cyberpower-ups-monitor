#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run this installer as root on the NUT collector host" >&2
  exit 1
fi
if [ "$#" -ne 4 ]; then
  echo "usage: $0 <monitor-url> <collector-name> <nut-ups> <token-file>" >&2
  exit 2
fi
if ! id nut >/dev/null 2>&1 || ! command -v upsc >/dev/null 2>&1; then
  echo "Network UPS Tools and its nut user must be installed first" >&2
  exit 1
fi

MONITOR_URL=$1
COLLECTOR_NAME=$2
NUT_UPS=$3
SOURCE_TOKEN=$4
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
APP_ROOT=/opt/cyberpower-ups-monitor-agent
CONFIG_ROOT=/etc/cyberpower-ups-monitor-agent

install -d -m 0755 "$APP_ROOT/src" "$CONFIG_ROOT"
rm -rf "$APP_ROOT/src/ups_monitor"
cp -R "$REPO_ROOT/src/ups_monitor" "$APP_ROOT/src/ups_monitor"
install -o root -g nut -m 0640 "$SOURCE_TOKEN" "$CONFIG_ROOT/ingest-token"

python3 - "$CONFIG_ROOT/agent.json" "$MONITOR_URL" "$COLLECTOR_NAME" \
  "$NUT_UPS" "$CONFIG_ROOT/ingest-token" <<'PY'
import json
import sys

path, server, collector, ups, token_file = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "server": server,
            "collector": collector,
            "token_file": token_file,
            "source": "nut",
            "ups": ups,
            "timeout_seconds": 15,
        },
        handle,
        indent=2,
    )
    handle.write("\n")
PY
chown root:nut "$CONFIG_ROOT/agent.json"
chmod 0640 "$CONFIG_ROOT/agent.json"

install -m 0644 "$SCRIPT_DIR/cyberpower-ups-monitor-agent.service" \
  /etc/systemd/system/cyberpower-ups-monitor-agent.service
install -m 0644 "$SCRIPT_DIR/cyberpower-ups-monitor-agent.timer" \
  /etc/systemd/system/cyberpower-ups-monitor-agent.timer
systemctl daemon-reload
systemctl enable --now cyberpower-ups-monitor-agent.timer
systemctl start cyberpower-ups-monitor-agent.service

echo "Installed read-only NUT collector: $COLLECTOR_NAME ($NUT_UPS)"
