#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <mobile-base-url>" >&2
  exit 2
fi

base_url="${1%/}"
max_attempts="${SMOKE_MAX_ATTEMPTS:-30}"
retry_seconds="${SMOKE_RETRY_SECONDS:-2}"

wait_for_status() {
  local path="$1"
  local expected_status="$2"
  local output_file="$3"
  local status=""

  for ((attempt = 1; attempt <= max_attempts; attempt += 1)); do
    status=$(curl --silent --show-error --output "$output_file" --write-out '%{http_code}' \
      --connect-timeout 5 --max-time 10 "${base_url}${path}" || true)
    if [[ "$status" == "$expected_status" ]]; then
      return 0
    fi
    sleep "$retry_seconds"
  done

  echo "smoke check failed: ${path} returned ${status}, expected ${expected_status}" >&2
  cat "$output_file" >&2 || true
  return 1
}

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

wait_for_status "/healthz" "200" "$work_dir/mobile-health.txt"
grep -q '^ok' "$work_dir/mobile-health.txt"

wait_for_status "/api/v1/health/live" "200" "$work_dir/api-live.json"
grep -q '"status":"ok"' "$work_dir/api-live.json"

wait_for_status "/api/v1/health/ready" "200" "$work_dir/api-ready.json"
grep -q '"status":"ready"' "$work_dir/api-ready.json"
grep -q '"migrations":"ok"' "$work_dir/api-ready.json"

wait_for_status "/api/v1/metrics" "404" "$work_dir/metrics.txt"
wait_for_status "/players/mobile-smoke-profile" "200" "$work_dir/deep-link.html"
grep -q 'id="root"' "$work_dir/deep-link.html"

echo "mobile deployment smoke checks passed: ${base_url}"
