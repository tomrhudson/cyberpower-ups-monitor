#!/bin/zsh
set -euo pipefail

LAUNCH_LABEL="io.github.cyberpower-ups-monitor.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/$LAUNCH_LABEL.plist"
launchctl bootout "gui/$(id -u)/$LAUNCH_LABEL" 2>/dev/null || true
rm -f "$PLIST_PATH"
rm -rf "$HOME/Library/Application Support/CyberPower UPS Monitor"
echo "Removed CyberPower UPS Monitor collector."
