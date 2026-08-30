#!/usr/bin/env bash
set -uo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
api_dir="$repo_root/apps/api"
python_bin="${API_DEV_PYTHON:-$api_dir/.venv/bin/python}"
api_host="${API_DEV_HOST:-127.0.0.1}"
api_port="${API_DEV_PORT:-8000}"

child_shutdown_timeout=5

main_pid=""
api_pid=""
cleanup_started=0
requested_exit_status=0

log() {
  printf '[dev-api] %s\n' "$*" >&2
}

request_stop() {
  local pid="$1"

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
  fi
}

wait_with_timeout() {
  local pid="$1"
  local label="$2"
  local timeout_seconds="$3"
  local watchdog_pid=""

  if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid" 2>/dev/null || true
    return
  fi

  (
    trap - EXIT INT TERM HUP
    sleep "$timeout_seconds"
    if kill -0 "$pid" 2>/dev/null; then
      log "$label did not stop within ${timeout_seconds}s; sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  ) &
  watchdog_pid=$!

  wait "$pid" 2>/dev/null || true
  kill -KILL "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true
}

api_command() {
  exec "$python_bin" -m uvicorn app.main:app \
    --host "$api_host" \
    --port "$api_port" \
    --reload
}

cleanup_all() {
  local api_to_stop="$api_pid"

  if ((cleanup_started)); then
    return
  fi
  cleanup_started=1
  api_pid=""

  request_stop "$api_to_stop"
  if [[ -n "$api_to_stop" ]]; then
    wait_with_timeout "$api_to_stop" "API server" "$child_shutdown_timeout"
  fi
}

handle_signal() {
  local exit_status="$1"
  local signal_name="$2"

  log "received $signal_name; stopping API"
  if ((requested_exit_status == 0)); then
    requested_exit_status=$exit_status
  fi
  request_stop "$api_pid"
}

main() {
  local api_status=0

  if [[ ! -x "$python_bin" ]]; then
    log "Python environment not found at $python_bin; run 'make install' first"
    return 127
  fi

  cd "$api_dir"
  main_pid=$$
  cleanup_started=0
  requested_exit_status=0
  api_pid=""

  trap cleanup_all EXIT
  trap 'handle_signal 130 INT' INT
  trap 'handle_signal 143 TERM' TERM
  trap 'handle_signal 129 HUP' HUP

  log "starting API on http://${api_host}:${api_port}"
  api_command &
  api_pid=$!

  wait "$api_pid"
  api_status=$?
  if ((requested_exit_status != 0)); then
    cleanup_all
    trap - EXIT INT TERM HUP
    return "$requested_exit_status"
  fi
  api_pid=""
  cleanup_all
  trap - EXIT INT TERM HUP
  return "$api_status"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
