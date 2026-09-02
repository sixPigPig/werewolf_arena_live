#!/usr/bin/env bash
# Idempotently start the local PostgreSQL cluster and ensure the `app` database
# exists with the password the application expects (postgres:postgres).
set -euo pipefail

log() { printf '[start-db] %s\n' "$*"; }

pg_version=$(pg_lsclusters -h 2>/dev/null | awk 'NR==1 {print $1}')
pg_version=${pg_version:-16}

if ! pg_lsclusters -h 2>/dev/null | grep -q online; then
  log "starting PostgreSQL cluster ${pg_version}/main"
  sudo pg_ctlcluster "$pg_version" main start
fi

# Wait for the socket to accept connections.
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q 2>/dev/null; then
    break
  fi
  sleep 1
done

sudo -u postgres psql -tAc "ALTER USER postgres WITH PASSWORD 'postgres';" >/dev/null
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='app'" | grep -q 1; then
  log "creating database 'app'"
  sudo -u postgres createdb app
fi

log "PostgreSQL is ready on 127.0.0.1:5432 (database 'app')"
