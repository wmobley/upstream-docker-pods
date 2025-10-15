"""
Utility script to block container startup until the target Postgres instance is reachable.
"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg import OperationalError


def wait_for_database() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required for API startup.")

    connect_timeout = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))
    max_attempts = int(os.environ.get("DB_MAX_ATTEMPTS", "30"))
    retry_delay = float(os.environ.get("DB_RETRY_DELAY", "2"))

    last_error: OperationalError | None = None

    parsed = urlparse(database_url)
    safe_target = (
        f"{parsed.scheme}://{parsed.username or '<user>'}@"
        f"{parsed.hostname or '<host>'}:{parsed.port or '<port>'}"
        f"/{parsed.path.lstrip('/') or '<database>'}"
    )

    print(f"[wait_for_db] Target: {safe_target}")

    # psycopg expects a standard postgresql:// DSN; strip any SQLAlchemy driver hint
    dsn = database_url
    driver_hint = "postgresql+psycopg://"
    if dsn.startswith(driver_hint):
        dsn = "postgresql://" + dsn[len(driver_hint) :]

    for attempt in range(1, max_attempts + 1):
        try:
            conn: Any = psycopg.connect(dsn, connect_timeout=connect_timeout)
            conn.close()
            print("[wait_for_db] Database connection established.")
            return
        except OperationalError as exc:
            last_error = exc
            print(f"[wait_for_db] Attempt {attempt}/{max_attempts} failed: {exc}")
            time.sleep(retry_delay)

    raise RuntimeError(
        "Unable to connect to Postgres after "
        f"{max_attempts} attempts. Last error: {last_error}"
    )


if __name__ == "__main__":
    wait_for_database()
