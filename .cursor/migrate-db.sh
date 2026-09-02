#!/usr/bin/env bash
# Idempotently run Alembic migrations to head.
#
# The migration chain has an ordering constraint: revision 20260727_46
# (add_player_model_provider) backfills virtual_player_profiles.model_provider
# from model_configurations and aborts if any seeded player has no matching
# model configuration. On a fresh database model_configurations is only
# populated by the application at runtime, so we seed it with the application's
# own idempotent bootstrap between revisions 45 and 46.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
api_dir="$repo_root/apps/api"
cd "$api_dir"

log() { printf '[migrate-db] %s\n' "$*"; }

alembic=".venv/bin/alembic"
python=".venv/bin/python"

# Upgrade only as far as revision 45. If the database is already past 45 this
# is a no-op (Alembic never downgrades on `upgrade`).
log "upgrading to revision 20260727_45"
"$alembic" upgrade 20260727_45

# Seed model_configurations from the environment providers. Idempotent: the
# bootstrap skips model ids that already exist.
log "bootstrapping model catalog"
"$python" - <<'PY'
from app.db.session import SessionLocal
from app.model_catalog.service import bootstrap_environment_catalog

db = SessionLocal()
try:
    bootstrap_environment_catalog(db)
    db.commit()
finally:
    db.close()
PY

log "upgrading to head"
"$alembic" upgrade head

log "database is at head"
