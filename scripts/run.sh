#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '%s [run.sh] %s\n' "$(date --utc +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

log "Starting application bootstrap."
log "Running Alembic migrations (heads)."
alembic upgrade heads
log "Migrations complete. Launching Uvicorn with args: $*"
exec uvicorn app.main:app "$@"
