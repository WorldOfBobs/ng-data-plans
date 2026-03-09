#!/usr/bin/env bash
# install-services.sh — register FX Bob instances as macOS launch agents
# Auto-starts on login, restarts on crash.
#
# Usage:
#   ./install-services.sh           — install all instances that have a token
#   ./install-services.sh nigeria   — install one
#   ./install-services.sh remove    — uninstall all

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$REPO/fx-tracker"
INST="$REPO/instances"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PYTHON="$CORE/venv/bin/python3"
TARGET="${1:-all}"

install_instance() {
  local name="$1"
  local dir="$INST/$name"
  local label="com.fxbob.$name"
  local dest="$LAUNCH_AGENTS/$label.plist"

  local token; token=$(grep "^BOT_TOKEN=" "$dir/.env" 2>/dev/null | cut -d= -f2-)
  if [[ "$token" == "REPLACE_WITH_"* || -z "$token" ]]; then
    echo "[$name] ⚠️  Token not set — skipping"
    return
  fi

  echo "[$name] Installing $label…"
  cat > "$dest" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$CORE/bot.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DATA_DIR</key>
    <string>$dir</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$CORE</string>
  <key>StandardOutPath</key>
  <string>$dir/bot.log</string>
  <key>StandardErrorPath</key>
  <string>$dir/bot.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>5</integer>
</dict>
</plist>
EOF
  launchctl unload "$dest" 2>/dev/null || true
  launchctl load -w "$dest"
  echo "  ✅ $label loaded"
}

remove_instance() {
  local name="$1"
  local label="com.fxbob.$name"
  local dest="$LAUNCH_AGENTS/$label.plist"
  if [[ -f "$dest" ]]; then
    launchctl unload "$dest" 2>/dev/null || true
    rm -f "$dest"
    echo "[$name] ✅ $label removed"
  fi
}

mkdir -p "$LAUNCH_AGENTS"

case "$TARGET" in
  remove)
    for name in $(ls "$INST"); do remove_instance "$name"; done
    echo "All services removed."
    ;;
  all)
    for name in $(ls "$INST"); do install_instance "$name"; done
    ;;
  *)
    install_instance "$TARGET"
    ;;
esac

echo ""
echo "Status: ./manage.sh status"
