#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '%s [upstream-entrypoint] %s\n' "$(date --utc +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

: "${DATABASE_URL:?DATABASE_URL environment variable must be set}"

log "Starting container for environment=${ENVIRONMENT:-unknown} (env=${ENV:-unknown})."
log "Waiting for database availability..."
python /upstream/scripts/wait_for_db.py
log "Database reachable. Launching application command: $*"

exec "$@"
