#!/usr/bin/env bash
# Per-boot startup: bring up PostgreSQL and apply any pending migrations before
# the service terminals launch. Dependency installation lives in install.sh.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PATH="$HOME/.local/bin:$PATH"

"$repo_root/.cursor/start-db.sh"
"$repo_root/.cursor/migrate-db.sh"
