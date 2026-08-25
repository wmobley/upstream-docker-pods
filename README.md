# Upstream API
[![DOI](https://zenodo.org/badge/1076824318.svg)](https://doi.org/10.5281/zenodo.17664688)


A RESTful API service for managing environmental sensor data and campaigns.

## Installation & Setup

1. Clone the repository
2. Install dependencies (Docker and Docker Compose required)
3. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
4. Create a `.env` file and set the environment variables. The sample defaults target a local Postgres instance (`localhost:5432`). If you want to connect to the Pods database instead, uncomment and populate the `PODS_DB_*` block in `.env.sample` (which also overrides `DATABASE_URL`):
   ```bash
   cp .env.sample .env
   ```
5. Build and run with Docker (recommended for local development):

   ```bash
   # Build the API image defined by Dockerfile (installs requirements into the container)
   docker compose build

   # Start API + database using the default stack
   docker compose up -d

   # Use an existing Postgres instance instead of the bundled db container
   # (ensure DATABASE_URL in .env points at the remote service)
   docker compose up -d --no-deps web
   ```

   The `web` service entrypoint waits for Postgres, then executes the default command—which runs `alembic upgrade heads` followed by Uvicorn on port 8000.

   For the slimmer dev stack in `docker-compose.dev.yml`, which targets whichever database `DATABASE_URL` references (Pods or local), start the service:

   ```bash
   # Launch only the API container; it will connect using DATABASE_URL from .env
   docker compose -f docker-compose.dev.yml up -d
   ```

   > Tip: the dev file no longer provisions a local Postgres container. Use the default `docker compose up -d` if you need an isolated local database for testing.

6. Optional: Run the API directly (without Docker) after installing dependencies:

   ```bash
   alembic upgrade heads
   fastapi dev app/main.py
   ```

## CKAN Integration

When `CKAN_URL` is configured and the request includes a Tapis token, the API can register station datasets and sensor resources in CKAN during station create, CSV upload, and station publish flows. Station publish fails before changing local publish state if CKAN sync reports errors.

For CSV uploads, CKAN synchronization is scheduled in a background task after the upload session is finalized, so CKAN network latency or failures do not block the upload response. The background task runs after the response is sent, uses its own database session, and only logs warnings. The Tapis token is passed in-memory and never persisted or logged. Because the task is not durable, a process restart immediately after the upload response may skip CKAN sync; the response reports the schedule status under `ckan_sync.status` (`scheduled`, `missing_tapis_token`, `ckan_disabled`, `not_finalized`, `skipped_incomplete_upload`, `already_finalized`, or `skipped_error`).

If CKAN reports that a dataset name is already in use, station publish returns a suggested alternate `ckan_dataset_name`. To update an existing matching Upstream station dataset instead, retry station publish with `patch_existing_ckan_dataset: true`.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Core API Endpoints

The service is mounted at `/api/v1`. Common read operations:

- `GET /api/v1/campaigns` — paginate campaigns, supports filters via query parameters
- `GET /api/v1/campaigns/{campaign_id}` — fetch campaign details including station summary
- `GET /api/v1/campaigns/{campaign_id}/stations` — list stations for a campaign
- `GET /api/v1/campaigns/{campaign_id}/stations/{station_id}` — station metadata plus sensor list
- `GET /api/v1/campaigns/{campaign_id}/stations/{station_id}/sensors` — enumerate sensors (filtering and sorting available)
- `GET /api/v1/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}/measurements` — retrieve measurements for a sensor

An interactive schema browser is available at `https://<host>/docs` (for example `https://infordisaster.pods.portals.tapis.io/docs`).

## CSV Upload

`POST /api/v1/uploadfile_csv/campaign/{campaign_id}/station/{station_id}/sensor` accepts two multipart files — a sensors CSV and a measurements CSV — and inserts measurements with `ON CONFLICT DO NOTHING` on `(sensorid, collectiontime)`.

**Timestamp format:** ISO-8601 — `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, optionally with `Z` or `+HH:MM` (e.g., `2024-01-01`, `2024-01-01 12:00:00`, `2024-01-01T12:00:00Z`, `2024-01-01 12:00:00-05:00`).

Every station declares an IANA `timezone` (required at creation, defaulting to `UTC` for stations created before this requirement). `collectiontime` values are stored as timezone-aware `TIMESTAMPTZ`: naive values in the measurements CSV are interpreted in the station's declared timezone, while values carrying a timezone (e.g. `Z` or `+00:00`) pass through unchanged.

Chunked uploads share a client-generated `upload_session_id`. Each request may set optional form fields:

- `upload_session_id` — identifies one logical upload spread across chunks.
- `chunk_index` — zero-based index of the current chunk.
- `total_chunks` — total number of chunks in the upload.
- `finalize_upload` (default `true`) — set `false` for every chunk except the last.

Measurements are inserted for every chunk. Expensive post-processing — sensor statistics refresh, station geometry refresh, and CKAN synchronization — runs only once, after the server verifies the session is complete (successful receipts exist for every chunk index `0..total_chunks-1` and the session is not already finalized). A finalizing chunk whose session cannot be verified complete returns `finalized=false` with `ckan_sync.status="skipped_incomplete_upload"`. A retried finalizing chunk for an already-finalized session returns `finalized=true`, `post_processing.status="already_finalized"`, and `ckan_sync.status="already_finalized"`. Legacy requests that omit `upload_session_id` are treated as a complete single-request upload.

The response includes per-chunk audit counts under `audit` (`measurement_rows_read`, `measurement_values_attempted`, `measurement_values_inserted`, `measurement_values_skipped_duplicate`, `sensor_alias_count`, `row_errors`), a `post_processing` block, and a `ckan_sync` block, while keeping the legacy keys (`Total sensors processed`, `Total measurements added to database`, `Data Processing time`, `errors`). `measurement_values_skipped_duplicate` is derived as attempted minus inserted.

## On-premise Environment

### Setting up environments

1. SSH to the VM with your TACC credentials:

   ```bash
   ssh <tacc_username>@upstream.pods.portals.tapis.io
   ```

2. Switch to root:

   ```bash
   sudo su
   ```

3. Enter to the prod directory or dev directory depending on what you want to do:

   ```bash
   cd ~/upstream-dev
   cd ~/upstream-prod
   ```

4. Change the IMAGE_TAG (commit hash, e.g. sha-a0fe1e7) in the .env file. You can find [here](https://github.com/In-For-Disaster-Analytics/upstream-docker/pkgs/container/upstream-docker) the latest commit hash.

   ```bash
   vim .env
   ```

5. Restart the containers:

   ```bash
   docker-compose up -d
   ```

## Deployment

There are two instances running on upstream.pods.portals.tapis.io:

- **Production**: https://upstreamapi.pods.portals.tapis.io/docs/
- **Development**: https://upstreamapi.pods.portals.tapis.io/dev/docs/

## Authentication

Tapis Pods header auth and JWT fallback (architecture, local testing, security considerations) are
documented in [`docs/auth/tapis-pods-auth.md`](../docs/auth/tapis-pods-auth.md) in the parent
`upstream` meta-repo.

## Database Migrations

The project uses Alembic for database migrations. Key commands:

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations (run all heads)
alembic upgrade heads

# Rollback last migration
alembic downgrade -1

# View migration history
alembic history
```

## Postgres Backups

Pod-hosted Upstream Postgres backups are documented in [../tapis-postgres-backup/README.md](/Users/wmobley/Documents/GitHub/upstream/tapis-postgres-backup/README.md). The backup tooling now lives in its own top-level directory so it can be operated from the VM without being mixed into the API service code.

## Seeding Development Data via API

The Alembic migrations insert sample campaigns, stations, sensors, and hourly measurements directly into the database. For workflows that need to exercise the API instead, use the helper script `scripts/seed_api_data.py`:

```bash
# Activate your virtualenv and ensure the API is running (defaults to http://localhost:8000).
python scripts/seed_api_data.py \
  --base-url http://localhost:8000/api/v1 \
  --token dev-token
```

The script:

- Creates the two sample campaigns and their associated stations if they are missing.
- Uploads sensors and 24 hours of hourly measurements for each station via the CSV upload endpoint.
- Accepts `--hours` to control the measurement window, `--dry-run` to preview actions, and `--skip-measurements` to load only metadata.

By default an Authorization header (`Bearer dev-token`) is sent; set `API_BEARER_TOKEN` or pass `--token` to supply a different credential, and `TAPIS_TOKEN` if you need the script to forward a real Tapis token.

## Database Schema

The following diagram shows the relationships between the main entities in the system:

```mermaid
classDiagram
    class Campaign {
        +int campaignid
        +string campaignname
        +string contactname
        +string contactemail
        +string description
        +datetime startdate
        +datetime enddate
        +string allocation
    }

    class Station {
        +int stationid
        +string stationname
        +string description
        +string contactname
        +string contactemail
        +bool active
        +datetime startdate
    }

    class Sensor {
        +string alias
        +string description
        +bool postprocess
        +string postprocessscript
        +string units
    }

    class Measurement {
        +int measurementid
        +int sensorid
        +string variablename
        +datetime collectiontime
        +string variabletype
        +string description
        +number measurementvalue
    }
    Campaign "1" --> "*" Station : has
    Station "1" --> "*" Sensor : contains
    Sensor "1" --> "*" Measurement : records
```

```

```
