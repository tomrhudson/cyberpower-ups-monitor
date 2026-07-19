#!/bin/zsh
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <monitor-url> <collector-name> <token-file>" >&2
  exit 2
fi

MONITOR_URL="$1"
COLLECTOR_NAME="$2"
SOURCE_TOKEN="$3"
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h:h}"
APP_DIR="$HOME/Library/Application Support/CyberPower UPS Monitor"
SOURCE_DIR="$APP_DIR/src"
CONFIG_PATH="$APP_DIR/agent.json"
TOKEN_PATH="$APP_DIR/ingest-token"
LOG_DIR="$HOME/Library/Logs/CyberPower UPS Monitor"
LAUNCH_LABEL="io.github.cyberpower-ups-monitor.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/$LAUNCH_LABEL.plist"

mkdir -p "$SOURCE_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"
rm -rf "$SOURCE_DIR/ups_monitor"
cp -R "$REPO_ROOT/src/ups_monitor" "$SOURCE_DIR/ups_monitor"
cp "$SOURCE_TOKEN" "$TOKEN_PATH"
chmod 600 "$TOKEN_PATH"

/usr/bin/python3 - "$CONFIG_PATH" "$MONITOR_URL" "$COLLECTOR_NAME" "$TOKEN_PATH" <<'PY'
import json
import sys

path, server, collector, token_file = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "server": server,
            "collector": collector,
            "token_file": token_file,
            "timeout_seconds": 15,
        },
        handle,
        indent=2,
    )
    handle.write("\n")
PY
chmod 600 "$CONFIG_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCH_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>ups_monitor.agent</string>
    <string>--config</string>
    <string>$CONFIG_PATH</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$SOURCE_DIR</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/agent.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/agent.err.log</string>
</dict>
</plist>
PLIST

chmod 600 "$PLIST_PATH"
launchctl bootout "gui/$(id -u)/$LAUNCH_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LAUNCH_LABEL"

echo "Installed read-only UPS collector: $COLLECTOR_NAME"
