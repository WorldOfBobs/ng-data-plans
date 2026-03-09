#!/usr/bin/env bash
# manage.sh — FX Bob multi-instance bot manager
#
# Architecture: one codebase (fx-tracker/), many instances (instances/<name>/)
# Each instance has its own .env + fx_rates.db
#
# Usage:
#   ./manage.sh status              — show all instances
#   ./manage.sh start               — start all ready instances
#   ./manage.sh start nigeria       — start one instance
#   ./manage.sh stop kenya          — stop one instance
#   ./manage.sh restart global      — restart one instance
#   ./manage.sh logs ghana          — tail logs for one instance
#   ./manage.sh add <name>          — scaffold a new instance folder

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$REPO_DIR/fx-tracker"
INST_DIR="$REPO_DIR/instances"
PYTHON="$CORE_DIR/venv/bin/python3"

# Discover all instances
all_instances() {
  ls "$INST_DIR" 2>/dev/null
}

# ── helpers ──────────────────────────────────

pidfile_of() { echo "$INST_DIR/$1/.bot.pid"; }
logfile_of()  { echo "$INST_DIR/$1/bot.log"; }

is_running() {
  local name="$1"
  local pidfile; pidfile=$(pidfile_of "$name")
  if [[ -f "$pidfile" ]]; then
    local pid; pid=$(<"$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "$pid"; return 0
    fi
    rm -f "$pidfile"
  fi
  return 1
}

bot_start() {
  local name="$1"
  local dir="$INST_DIR/$name"

  if pid=$(is_running "$name"); then
    echo "[$name] Already running (PID $pid)"
    return
  fi

  if [[ ! -f "$dir/.env" ]]; then
    echo "[$name] ERROR: $dir/.env not found"
    return
  fi

  local token; token=$(grep "^BOT_TOKEN=" "$dir/.env" 2>/dev/null | cut -d= -f2- || true)
  if [[ "$token" == "REPLACE_WITH_"* || -z "$token" ]]; then
    echo "[$name] ⚠️  Token not set — skipping (edit $dir/.env)"
    return
  fi

  echo "[$name] Starting…"
  DATA_DIR="$dir" nohup "$PYTHON" "$CORE_DIR/bot.py" >> "$(logfile_of "$name")" 2>&1 &
  echo $! > "$(pidfile_of "$name")"
  echo "[$name] ✅ Started PID $!"
}

bot_stop() {
  local name="$1"
  local pidfile; pidfile=$(pidfile_of "$name")
  if pid=$(is_running "$name"); then
    echo "[$name] Stopping PID $pid…"
    kill "$pid" 2>/dev/null || true
    sleep 1; kill -9 "$pid" 2>/dev/null || true
    rm -f "$pidfile"
    echo "[$name] Stopped."
  else
    echo "[$name] Not running."
  fi
}

bot_status() {
  local name="$1"
  local dir="$INST_DIR/$name"
  local token; token=$(grep "^BOT_TOKEN=" "$dir/.env" 2>/dev/null | cut -d= -f2- | head -c 20 || true)
  local handle; handle=$(grep "^BOT_HANDLE=" "$dir/.env" 2>/dev/null | cut -d= -f2- || true)
  local country; country=$(grep "^DEFAULT_COUNTRY=" "$dir/.env" 2>/dev/null | cut -d= -f2- || true)

  if [[ "$token" == "REPLACE_WITH_"* || -z "$token" ]]; then
    echo "[$name] ⏳  Token not set yet — needs BotFather  handle=$handle"
    return
  fi

  if pid=$(is_running "$name"); then
    echo "[$name] ✅  Running  PID=$pid  handle=$handle  country=$country  token=${token}…"
  else
    echo "[$name] 🔴  Stopped  handle=$handle  country=$country"
  fi
}

bot_logs() {
  local name="$1"
  local logfile; logfile=$(logfile_of "$name")
  if [[ -f "$logfile" ]]; then
    echo "── $name ($INST_DIR/$name) ──────────────"
    tail -30 "$logfile"
  else
    echo "[$name] No log yet."
  fi
}

bot_add() {
  local name="$1"
  local dir="$INST_DIR/$name"
  if [[ -d "$dir" ]]; then
    echo "[$name] Instance already exists at $dir"
    return
  fi
  mkdir -p "$dir"
  cat > "$dir/.env" <<EOF
BOT_TOKEN=REPLACE_WITH_${name^^}_TOKEN
DEFAULT_COUNTRY=
BOT_HANDLE=@${name^}FXBot
MAIN_BOT_HANDLE=@FXbob_bot
POLL_INTERVAL_SECONDS=900
WISE_AFFILIATE_URL=
REMITLY_AFFILIATE_URL=
EOF
  echo "[$name] ✅  Created $dir/.env — fill in BOT_TOKEN and DEFAULT_COUNTRY"
}

# ── dispatch ─────────────────────────────────

CMD="${1:-status}"
TARGET="${2:-all}"

run_for() {
  local fn="$1"
  if [[ "$TARGET" == "all" ]]; then
    for name in $(all_instances); do
      "$fn" "$name"
    done
  else
    "$fn" "$TARGET"
  fi
}

case "$CMD" in
  start)   run_for bot_start   ;;
  stop)    run_for bot_stop    ;;
  restart) run_for bot_stop; sleep 1; run_for bot_start ;;
  status)  run_for bot_status  ;;
  logs)    run_for bot_logs    ;;
  add)
    [[ -z "${2:-}" ]] && echo "Usage: $0 add <name>" && exit 1
    bot_add "$2"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|add} [instance|all]"
    exit 1
    ;;
esac
