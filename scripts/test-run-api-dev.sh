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
api_command() { return 23; }
main
BASH
assert_status 23 "$?" "API exit propagation"

bash -s "$runner" <<'BASH'
export API_DEV_PYTHON="$BASH"
source "$1"
child_shutdown_timeout=1
api_command() { exec sleep 30; }
(sleep 0.5; kill -TERM "$$") &
main
BASH
assert_status 143 "$?" "TERM propagation"

printf 'run-api-dev lifecycle tests passed\n'
