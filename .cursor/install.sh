#!/usr/bin/env bash
# Idempotent repository bootstrap for the werewolf_arena_live monorepo.
# Installs toolchains, project dependencies, and prepares the local database.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

log() { printf '[install] %s\n' "$*"; }

# --- uv (Python package/venv manager) -------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  log "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# --- PostgreSQL server ------------------------------------------------------
if ! command -v psql >/dev/null 2>&1; then
  log "installing PostgreSQL"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib
fi

# --- Environment files (never overwrite existing local edits) --------------
if [[ ! -f apps/api/.env ]]; then
  log "creating apps/api/.env from example"
  cp apps/api/.env.example apps/api/.env
fi
if [[ ! -f apps/admin-web/.env ]]; then
  log "creating apps/admin-web/.env from example"
  cp apps/admin-web/.env.example apps/admin-web/.env
fi

# --- Python + JS dependencies ----------------------------------------------
log "syncing Python dependencies (uv sync)"
(cd apps/api && uv sync)

log "installing JS dependencies (pnpm install)"
pnpm install

# --- Database bring-up and migrations --------------------------------------
"$repo_root/.cursor/start-db.sh"
"$repo_root/.cursor/migrate-db.sh"

log "install complete"
