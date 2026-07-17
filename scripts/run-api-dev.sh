#!/usr/bin/env bash
set -uo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
api_dir="$repo_root/apps/api"
python_bin="${API_DEV_PYTHON:-$api_dir/.venv/bin/python}"
api_host="${API_DEV_HOST:-127.0.0.1}"
api_port="${API_DEV_PORT:-8000}"

worker_restart_limit=5
worker_stable_seconds=30
worker_restart_max_delay=8
child_shutdown_timeout=5
supervisor_shutdown_timeout=8

main_pid=""
api_pid=""
supervisor_pid=""
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
    trap - EXIT INT TERM HUP USR1
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

worker_command() {
  exec "$python_bin" -m app.cli run-live-voice-materializer
}

api_command() {
  exec "$python_bin" -m uvicorn app.main:app \
    --host "$api_host" \
    --port "$api_port" \
    --reload
}

supervise_worker() (
  active_pid=""
  active_label=""
  notify_main=1
  stopping=0
  failure_count=0
  restart_delay=1
  started_at=0
  runtime_seconds=0
  worker_status=0

  supervisor_cleanup() {
    local pid="$active_pid"
    local label="$active_label"

    active_pid=""
    active_label=""
    if [[ -n "$pid" ]]; then
      request_stop "$pid"
      wait_with_timeout "$pid" "$label" "$child_shutdown_timeout"
    fi
  }

  supervisor_signal() {
    notify_main=0
    stopping=1
    request_stop "$active_pid"
  }

  supervisor_exit() {
    local exit_status=$?

    supervisor_cleanup
    if ((notify_main)); then
      kill -USR1 "$main_pid" 2>/dev/null || true
    fi
    return "$exit_status"
  }

  trap supervisor_exit EXIT
  trap supervisor_signal INT TERM HUP

  while true; do
    if ((stopping)); then
      supervisor_cleanup
      exit 0
    fi

    started_at=$SECONDS
    worker_command &
    active_pid=$!
    active_label="live voice materializer"

    wait "$active_pid"
    worker_status=$?
    if ((stopping)); then
      supervisor_cleanup
      exit 0
    fi
    active_pid=""
    active_label=""
    runtime_seconds=$((SECONDS - started_at))

    if ((runtime_seconds >= worker_stable_seconds)); then
      failure_count=1
      restart_delay=1
    else
      failure_count=$((failure_count + 1))
    fi

    if ((failure_count >= worker_restart_limit)); then
      log "live voice materializer exited with status $worker_status after ${runtime_seconds}s; giving up after $failure_count rapid failures"
      exit 1
    fi

    log "live voice materializer exited with status $worker_status after ${runtime_seconds}s; restarting in ${restart_delay}s (failure $failure_count/$worker_restart_limit)"
    sleep "$restart_delay" &
    active_pid=$!
    active_label="worker restart delay"
    wait "$active_pid" 2>/dev/null || true
    if ((stopping)); then
      supervisor_cleanup
      exit 0
    fi
    active_pid=""
    active_label=""

    restart_delay=$((restart_delay * 2))
    if ((restart_delay > worker_restart_max_delay)); then
      restart_delay=$worker_restart_max_delay
    fi
  done
)

cleanup_all() {
  local api_to_stop="$api_pid"
  local supervisor_to_stop="$supervisor_pid"

  if ((cleanup_started)); then
    return
  fi
  cleanup_started=1
  api_pid=""
  supervisor_pid=""

  request_stop "$supervisor_to_stop"
  request_stop "$api_to_stop"

  if [[ -n "$supervisor_to_stop" ]]; then
    wait_with_timeout "$supervisor_to_stop" "live voice materializer supervisor" "$supervisor_shutdown_timeout"
  fi
  if [[ -n "$api_to_stop" ]]; then
    wait_with_timeout "$api_to_stop" "API server" "$child_shutdown_timeout"
  fi
}

handle_signal() {
  local exit_status="$1"
  local signal_name="$2"

  log "received $signal_name; stopping API and worker"
  if ((requested_exit_status == 0)); then
    requested_exit_status=$exit_status
  fi
  request_stop "$supervisor_pid"
  request_stop "$api_pid"
}

handle_supervisor_failure() {
  log "live voice materializer supervisor stopped; stopping API"
  requested_exit_status=1
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
  supervisor_pid=""

  trap cleanup_all EXIT
  trap 'handle_signal 130 INT' INT
  trap 'handle_signal 143 TERM' TERM
  trap 'handle_signal 129 HUP' HUP
  trap handle_supervisor_failure USR1

  log "starting API on http://${api_host}:${api_port} with live voice materializer supervision"
  supervise_worker &
  supervisor_pid=$!
  api_command &
  api_pid=$!

  wait "$api_pid"
  api_status=$?
  if ((requested_exit_status != 0)); then
    cleanup_all
    trap - EXIT INT TERM HUP USR1
    return "$requested_exit_status"
  fi
  api_pid=""
  cleanup_all
  trap - EXIT INT TERM HUP USR1
  return "$api_status"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
