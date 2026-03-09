#!/usr/bin/env bash
# manage.sh — FX Bob bot manager
# Usage: ./manage.sh [start|stop|restart|status|logs] [nigeria|global|all]
#
# nigeria  → fx-tracker/          (@NigeriaFXBob, DEFAULT_COUNTRY=NG)
# global   → fx-tracker-global/   (@FXbob,        DEFAULT_COUNTRY=ALL)
# all      → both (default)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BOTS=(
  "nigeria:$REPO_DIR/fx-tracker"
  "global:$REPO_DIR/fx-tracker-global"
)

# ── helpers ──────────────────────────────────

pid_of() {
  local dir="$1"
  pgrep -f "python3 bot.py" | while read -r p; do
    if ls -l /proc/$p/cwd 2>/dev/null | grep -q "$dir"; then
      echo "$p"; return
    fi
    # macOS: use lsof
    if lsof -p "$p" 2>/dev/null | awk '{print $9}' | grep -q "$dir"; then
      echo "$p"; return
    fi
  done
}

is_running() {
  local dir="$1"
  # Check by logfile PID stamp
  local pidfile="$dir/.bot.pid"
  if [[ -f "$pidfile" ]]; then
    local pid; pid=$(<"$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "$pid"; return 0
    fi
  fi
  return 1
}

bot_start() {
  local name="$1" dir="$2"

  if pid=$(is_running "$dir"); then
    echo "[$name] Already running (PID $pid)"
    return
  fi

  if [[ ! -f "$dir/.env" ]]; then
    echo "[$name] ERROR: $dir/.env not found — skipping"
    return
  fi

  # Check token is set
  local token; token=$(grep "^BOT_TOKEN=" "$dir/.env" | cut -d= -f2-)
  if [[ "$token" == "REPLACE_WITH_"* || -z "$token" ]]; then
    echo "[$name] WARNING: BOT_TOKEN not set in $dir/.env — skipping"
    return
  fi

  echo "[$name] Starting…"
  cd "$dir"
  nohup venv/bin/python3 bot.py >> "$dir/bot.log" 2>&1 &
  echo $! > "$dir/.bot.pid"
  echo "[$name] Started PID $!"
}

bot_stop() {
  local name="$1" dir="$2"
  local pidfile="$dir/.bot.pid"

  if pid=$(is_running "$dir"); then
    echo "[$name] Stopping PID $pid…"
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$pidfile"
    echo "[$name] Stopped."
  else
    echo "[$name] Not running."
    rm -f "$pidfile"
  fi
}

bot_status() {
  local name="$1" dir="$2"
  if pid=$(is_running "$dir"); then
    local token; token=$(grep "^BOT_TOKEN=" "$dir/.env" 2>/dev/null | cut -d= -f2- | head -c 20)
    local country; country=$(grep "^DEFAULT_COUNTRY=" "$dir/.env" 2>/dev/null | cut -d= -f2-)
    echo "[$name] ✅  Running  PID=$pid  country=$country  token=${token}…"
  else
    echo "[$name] 🔴  Stopped"
  fi
}

bot_logs() {
  local name="$1" dir="$2"
  local logfile="$dir/bot.log"
  if [[ -f "$logfile" ]]; then
    echo "── $name ────────────────────────────"
    tail -30 "$logfile"
  else
    echo "[$name] No log file yet."
  fi
}

# ── dispatch ─────────────────────────────────

CMD="${1:-status}"
TARGET="${2:-all}"

run_for() {
  local fn="$1"
  for entry in "${BOTS[@]}"; do
    local name="${entry%%:*}"
    local dir="${entry##*:}"
    if [[ "$TARGET" == "all" || "$TARGET" == "$name" ]]; then
      "$fn" "$name" "$dir"
    fi
  done
}

case "$CMD" in
  start)   run_for bot_start   ;;
  stop)    run_for bot_stop    ;;
  restart) run_for bot_stop; sleep 1; run_for bot_start ;;
  status)  run_for bot_status  ;;
  logs)    run_for bot_logs    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs} [nigeria|global|all]"
    exit 1
    ;;
esac
