#!/usr/bin/env bash
set -uo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
runner="$script_dir/run-api-dev.sh"

assert_status() {
  local expected="$1"
  local actual="$2"
  local scenario="$3"

  if [[ "$actual" -ne "$expected" ]]; then
    printf '%s: expected status %s, got %s\n' "$scenario" "$expected" "$actual" >&2
    exit 1
  fi
}

bash -s "$runner" <<'BASH'
export API_DEV_PYTHON="$BASH"
source "$1"
child_shutdown_timeout=1
supervisor_shutdown_timeout=2
worker_command() { exec sleep 30; }
api_command() { return 23; }
main
BASH
assert_status 23 "$?" "API exit propagation"

bash -s "$runner" <<'BASH'
export API_DEV_PYTHON="$BASH"
source "$1"
child_shutdown_timeout=1
supervisor_shutdown_timeout=2
worker_command() { exec sleep 30; }
api_command() { exec sleep 30; }
(sleep 0.5; kill -TERM "$$") &
main
BASH
assert_status 143 "$?" "TERM propagation"

bash -s "$runner" <<'BASH'
export API_DEV_PYTHON="$BASH"
source "$1"
worker_restart_limit=3
worker_restart_max_delay=1
child_shutdown_timeout=1
supervisor_shutdown_timeout=2
worker_command() { return 7; }
api_command() { exec sleep 30; }
main
BASH
assert_status 1 "$?" "worker crash-loop shutdown"

bash -s "$runner" <<'BASH'
export API_DEV_PYTHON="$BASH"
source "$1"
child_shutdown_timeout=1
supervisor_shutdown_timeout=2
worker_command() {
  if ((failure_count == 0)); then
    return 9
  fi
  exec sleep 30
}
api_command() { exec sleep 2; }
main
BASH
assert_status 0 "$?" "worker restart recovery"

printf 'run-api-dev lifecycle tests passed\n'
