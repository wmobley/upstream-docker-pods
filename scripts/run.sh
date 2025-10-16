#!/usr/bin/env bash

set -euo pipefail

alembic upgrade heads
exec uvicorn app.main:app "$@"
