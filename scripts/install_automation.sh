#!/bin/bash
# One-command installer for the "call ends -> summary in inbox" automation.
#
# Installs a launchd agent that runs the watcher whenever ~/Documents/Zoom
# changes, plus a sweep every 5 minutes as a safety net. Existing recordings
# are grandfathered so only future calls are processed automatically.
#
# Usage:   bash scripts/install_automation.sh
# Remove:  bash scripts/install_automation.sh uninstall

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LABEL="com.callprocessor.watcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$REPO/logs"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Automation removed. (Recordings and outputs are untouched.)"
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  echo "ERROR: $PY not found. Run the setup steps in README.md first." >&2
  exit 1
fi

mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"

echo "Grandfathering existing recordings (only future calls will auto-process)..."
"$PY" "$REPO/scripts/watch_and_process.py" --mark-existing

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$REPO/scripts/watch_and_process.py</string>
    </array>
    <key>WorkingDirectory</key><string>$REPO</string>
    <key>WatchPaths</key>
    <array><string>$HOME/Documents/Zoom</string></array>
    <key>StartInterval</key><integer>300</integer>
    <key>RunAtLoad</key><true/>
    <key>ThrottleInterval</key><integer>60</integer>
    <key>StandardOutPath</key><string>$LOGDIR/watcher.log</string>
    <key>StandardErrorPath</key><string>$LOGDIR/watcher.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Automation installed. From now on: finish a Zoom call, and within a few"
echo "minutes the transcript + summary are generated and the summary is emailed"
echo "(if email is enabled in config.yaml)."
echo ""
echo "Watch it work:   tail -f $LOGDIR/watcher.log"
echo "Turn it off:     bash scripts/install_automation.sh uninstall"
