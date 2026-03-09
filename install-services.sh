#!/usr/bin/env bash
# install-services.sh — register FX Bob bots as macOS launch agents
# They will auto-start on login and restart automatically on crash.
#
# Usage:
#   ./install-services.sh          — install both
#   ./install-services.sh nigeria  — install only Nigeria bot
#   ./install-services.sh global   — install only global bot
#   ./install-services.sh remove   — uninstall both

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
TARGET="${1:-all}"

install_agent() {
  local label="$1"
  local plist="$REPO/launchd/${label}.plist"
  local dest="$LAUNCH_AGENTS/${label}.plist"

  echo "Installing $label…"
  cp "$plist" "$dest"
  launchctl unload "$dest" 2>/dev/null || true
  launchctl load -w "$dest"
  echo "  ✅ $label loaded"
}

remove_agent() {
  local label="$1"
  local dest="$LAUNCH_AGENTS/${label}.plist"

  if [[ -f "$dest" ]]; then
    echo "Removing $label…"
    launchctl unload "$dest" 2>/dev/null || true
    rm -f "$dest"
    echo "  ✅ $label removed"
  else
    echo "  $label not installed, skipping"
  fi
}

mkdir -p "$LAUNCH_AGENTS"

case "$TARGET" in
  all)
    install_agent "com.fxbob.nigeria"
    install_agent "com.fxbob.global"
    ;;
  nigeria)
    install_agent "com.fxbob.nigeria"
    ;;
  global)
    install_agent "com.fxbob.global"
    ;;
  remove)
    remove_agent "com.fxbob.nigeria"
    remove_agent "com.fxbob.global"
    echo "All services removed."
    ;;
  *)
    echo "Usage: $0 [all|nigeria|global|remove]"
    exit 1
    ;;
esac

echo ""
echo "Check status with: ./manage.sh status"
