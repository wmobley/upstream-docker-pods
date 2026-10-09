# Mobile Sniffer Production Rollout Without Data Loss

## Status

In Review

## Objective

Plan a safe production rollout for the `mobilesnifferapi` and
`mobilesnifferpostgres` Tapis Pods while preserving the existing production
database, avoiding an unvalidated partition cutover, and providing a tested
rollback path.

## User need

**Primary user:** The Upstream service operator responsible for the Mobile Sniffer production Pods.

**Secondary users:** Researchers and API clients that read the existing Mobile Sniffer campaigns,
stations, sensors, measurements, and notes.

**Job-to-be-done:** Promote the tested upload and query behavior to production without losing or
making existing sensor data inaccessible.

**Current pain:** The develop implementation has been exercised against a large historical load,
but the production Pods still use the older unpartitioned schema and the production deployment
workflow is not yet a separately approved, gated path.

**Definition of success:** Production remains readable throughout the rollout, existing row and
referential-integrity counts are unchanged, representative API queries continue to succeed within
the agreed latency budget, and rollback can restore the previous image without restoring the
database from backup.

## Current code/system summary

### Production Pods inspected on 2026-10-09

- `mobilesnifferpostgres` is `AVAILABLE`, uses `postgis/postgis:17-3.5`, and mounts the durable
  `mobilesniffervolume` at `/var/lib/postgresql/data`.
- The production Postgres Pod has a 6,144 MiB memory limit and 4,000 millicpu limit.
- `mobilesnifferapi` is `AVAILABLE`, uses `ghcr.io/wmobley/upstream-docker-pods:sha-5c974d4`,
  has a 3,072 MiB memory limit, and runs `alembic upgrade heads` before Uvicorn.
- The production API Pod has `--reload` in its startup command; this should be removed or
  explicitly accepted as a separate production-hardening decision.
- The requested production scope contains the API and Postgres Pods only; no production worker
  Pod was included in the inspected target set. Any durable asynchronous import/post-processing
  worker is therefore a separate deployment decision.
- Production currently has one campaign, two stations, 1,552 sensors, 10,025,920 measurements,
  and zero notes.
- Production is on Alembic revision `9e1f2a3b4c5d`; `measurement_identity` does not exist.
- The mounted volume reports 319 GB total, 275 GB used, and 45 GB available. This is not enough
  headroom to assume that a full shadow-table/index/WAL migration is safe.

### Current evidence

- The develop full-file run committed all 17 data chunks and the final 4,680-row chunk, with no
  upload errors. Its final audit receipt remained unfinalized after the client connection closed
  while long sensor-statistics post-processing continued; this is an operational readiness issue,
  not evidence that the measurement rows were lost.
- Develop warm API query benchmarks returned HTTP 200 with medians of approximately 0.72–0.93
  seconds for representative measurement-list, downsampled, and confidence-interval reads.
- The current production API baseline returned HTTP 200 with medians of approximately 0.39–0.61
  seconds for comparable reads on sensor `986`. These are warm-cache, single-sensor timings and
  are a baseline rather than a direct apples-to-apples regression result.
- The current branch contains the develop-only identity/partition implementation at commit
  `2a1b240`. The existing design explicitly defers production rollout and physical cutover.
- The current develop database contains a separate load-test dataset and must not be treated as a
  production clone. A production-shaped rehearsal requires restoring a verified production backup
  into an isolated develop database/volume or deliberately wiping the disposable develop target.
- On 2026-10-09, a production-shaped rehearsal was restored into isolated Pods
  `mobilesnifferrehearsalpostgres` and `mobilesnifferrehearsalapi`; the existing develop Pods were
  left unchanged. The local custom-format dump was 183,645,762 bytes and passed `pg_restore --list`.
- The restored rehearsal matched production on PostgreSQL 17.5, Alembic revision, campaign/station/
  sensor/measurement/note counts, and measurement ID bounds. The identity seed reached exact parity
  at 10,025,920 rows. The 16-partition shadow reached `prepared` with 48 index steps completed.
- The isolated cutover completed with `measurements_legacy_20261006` retained. Live, legacy, and
  identity counts were each 10,025,920, and the notes foreign key was present. Authenticated API
  reads and note lookup returned HTTP 200; warm medians after cutover were approximately 0.192 s
  (100 measurements), 0.305 s (1,000 measurements), and 0.162 s (hourly confidence intervals).
- Tapis Files rejected creation of the new dated backup directory, so the approved rehearsal source
  backup is currently retained locally at `/private/tmp/mobilesniffer-production-20261009/` with
  restricted permissions. It has not been copied back to production.
- The rollback rehearsal also completed successfully. The live table returned to the original
  unpartitioned table with 10,025,920 rows, the retained failed partitioned copy had 10,025,920
  rows across 16 child partitions, the identity registry remained at 10,025,920 rows, the notes
  foreign key remained valid, and an authenticated API measurement read returned HTTP 200 after
  the API restart.
- Final rehearsal counters on the 6,144 MiB Postgres Pod were approximately 4.85 GiB database
  size, 2.01 GiB live-table size, 2.04 GiB retained partitioned-child size, 776 MiB identity-table
  size, and 8.01 GiB cumulative WAL bytes. These are end-state counters, not peak memory or a
  production capacity approval.

### Immediate production blocker

The current identity migration creates an empty `measurement_identity` table and intentionally
does not seed existing measurements during Alembic startup. The current application compatibility
code resolves ID-only measurement reads through `measurement_identity`. Deploying that image
directly to production would therefore risk making existing measurement-ID and note lookups fail
before the identity table is seeded and its relationships are validated.

## Proposed design

Use a staging rehearsal followed by two separately approved production phases.

### Phase 0 — production-shaped develop rehearsal

Use develop to validate the migration against the real production schema and data shape before
any production schema change.

1. Capture a verified production backup, including database globals/roles separately from the
   application data dump. Do not copy production secrets or replace the production volume.
2. Preserve the current develop benchmark evidence, then restore the production data into an
   isolated develop database/volume. If an isolated target is unavailable, explicitly approve
   wiping the disposable develop database; never mix the production clone with the current load
   test dataset.
3. Keep the restored unpartitioned `measurements` table as the source. Apply the compatibility
   migration, seed `measurement_identity` in bounded resumable batches, install the trigger, and
   validate counts, IDs, sequences, notes, and duplicate behavior.
4. Build the partitioned shadow table, validate it, and rehearse the maintenance-window cutover.
5. Exercise API reads, ID lookups, notes, a canary write, restart/resume behavior, and rollback
   while the original restored table remains available.
6. Record elapsed time, peak memory, WAL, disk use, query latency, and the exact commands needed
   for production. This produces a runbook; it does not authorize production changes.

The validated develop database must not be copied back as a blind volume replacement. Production
may receive new writes, has different Tapis volume identity and secrets, and requires its own
backup, maintenance window, and post-cutover validation. The production operation should repeat
the tested migration/cutover against a fresh production snapshot, or use a deliberately planned
full logical restore with a complete outage and reconciliation.

### Phase 1 — production-safe compatibility and API rollout

Phase 1 must not replace or repartition the live `measurements` table.

1. Add a production-safe compatibility mode so the API can operate against the current
   unpartitioned production table without assuming that `measurement_identity` is populated.
   The implemented repository path prefers an identity row when present, then falls back to the
   legacy `measurements.sensorid` lookup when the registry is empty or the table has not been
   migrated. Measurement-scoped note listing likewise joins the legacy measurements table, so
   existing note behavior remains available throughout the compatibility window.
2. Keep the historical backfill and partitioned storage flags disabled in production.
3. Build the candidate image through CI, record its immutable commit tag and image digest, and
   deploy only through a manually approved production environment. Do not auto-deploy feature
   branches or `main` to these Pods.
4. Before any production database mutation, create and verify a restorable database backup or
   volume snapshot. Record row counts, ID bounds, sequence state, schema revision, and storage
   headroom.
5. During a scheduled maintenance window, update the API Pod while preserving its database URL,
   secrets, CORS settings, networking, resource settings, and durable volume configuration.
6. Run migrations only if they are additive and explicitly compatible with the selected legacy
   storage mode. Do not run the develop-only seed or partition cutover helper in production.
7. Run authenticated smoke tests, measurement-ID lookup tests, note tests, duplicate-write tests,
   and the read-latency benchmark. Compare results with the captured production baseline.
8. Observe the API and database before enabling any new production import mode.

The recommended Phase 1 release is an API/application compatibility release, not a production
partition migration. If the compatibility mode cannot be implemented cleanly, stop rather than
deploying the current `2a1b240` image unchanged.

### Phase 2 — optional physical partition migration

Phase 2 is a separate production change and is not part of the first rollout.

1. Increase database memory and storage headroom based on a production-sized rehearsal; the
   current 6 GB memory limit and 45 GB available volume space are not an approved migration
   envelope.
2. Provide a production-safe, resumable identity seed command with an explicit production guard,
   advisory lock, bounded commits, progress state, and restart behavior.
3. Pause all measurement writers for the seed/trigger transition, seed and validate every existing
   measurement identity, then install the identity-registration trigger on the live table.
4. Build the partitioned shadow table in bounded, resumable steps while the old table remains the
   live source. Validate counts, IDs, sensor relationships, uniqueness, notes, indexes, and
   representative query results.
5. Schedule a second maintenance window, quiesce writes, acquire the migration lock, perform the
   final catch-up, and cut over atomically.
6. Restart the API against the cutover schema, run the full smoke/benchmark suite, and retain the
   old table under a recovery name for a defined soak period.
7. Remove the old table only after an explicit later approval and a verified backup.

## Files likely affected

Phase 1 implementation is expected to touch:

- `app/db/repositories/measurement_repository.py`
- `app/db/repositories/note_repository.py`
- `app/db/models/measurement.py`
- `app/db/models/note.py`
- `app/db/models/measurement_identity.py`
- one or more Alembic migrations under `alembic/versions/`
- a production-safe identity compatibility/seed helper under `scripts/`
- focused production-mode and migration tests under `tests/`
- `.github/workflows/build-docker-image.yaml` for a manually gated production deployment job
- `README.md` and the relevant DSO Architecture service/CI documentation

The current compatibility implementation is limited to the repository fallback and focused tests;
it does not change the production migration, deployment workflow, or partition/cutover helpers.

Phase 2 would additionally affect the partition migration helper and its production runbook.

## API/schema changes

Phase 1 should preserve all public routes and response shapes.

Potential internal/schema changes require explicit review:

- A compatibility flag or storage-mode setting may be added, defaulting to the current
  unpartitioned behavior in production.
- If `measurement_identity` is introduced in Phase 1, it must be fully seeded and validated before
  any production request depends on it.
- Existing `notes.measurement_id` behavior must remain valid during Phase 1. Do not move the note
  foreign key to the identity table until the identity table is complete and the migration has
  been tested against production-shaped data.
- Phase 2 would add the sensor-partitioned physical table and identity-table foreign-key model;
  this is not a Phase 1 schema change.

## Data flow

### Phase 1

```text
verified backup
      |
      v
production compatibility migration (if needed)
      |
      v
mobilesnifferapi restart -> existing unpartitioned measurements table
      |
      +--> authenticated smoke tests
      +--> ID and note lookup tests
      +--> read-latency benchmark
      +--> row-count / sequence / FK validation
```

### Phase 2

```text
live unpartitioned measurements
      |
      +--> bounded identity seed + validation
      +--> shadow partition copy + local indexes
      +--> count/ID/FK/query validation
      +--> write quiescence + final catch-up
      +--> atomic cutover
      +--> API restart and soak
```

## Risks and tradeoffs

- **Empty identity table risk:** Deploying the current compatibility code unchanged can break
  existing ID-only lookups because production has no identity rows.
- **Storage risk:** The production volume reports only 45 GB free. Shadow tables, indexes, WAL,
  and temporary sort space can exceed that even if the final table is small.
- **Memory risk:** Production Postgres is limited to 6 GB, while the develop load test used a
  larger memory envelope. Develop success does not establish production migration safety.
- **Downtime risk:** The production stack has one API Pod and one Postgres Pod; a safe cutover
  requires a maintenance window unless a future dual-write/CDC design is approved.
- **Startup migration risk:** The API runs Alembic automatically before serving requests, so an
  incompatible migration can affect production before health checks pass.
- **Finalization risk:** The develop full-file run committed data but did not produce a finalized
  receipt after the client disconnected during expensive statistics work. Production should not
  rely on a long synchronous finalizing request without a durable asynchronous completion path.
- **Rollback boundary:** Reverting the API image is fast; undoing a physical database cutover is
  not. The old table and a verified backup must remain until the soak period ends.
- **Operational tradeoff:** Phase 1 provides a smaller, safer production change but does not
  immediately deliver partitioned storage. Phase 2 offers the storage optimization but requires
  more capacity, downtime, validation, and rollback preparation.
- **Clone tradeoff:** A logical production restore into develop is slower than a volume clone but
  avoids coupling production to develop's volume identity, credentials, and physical state. A
  volume clone is acceptable only if Tapis provides a tested snapshot/clone and restore workflow.

## Alternatives considered

- **Deploy the current develop image directly:** Rejected because the empty identity-table hazard
  is not safe for the existing production data.
- **Run the develop partition seed/cutover scripts in production:** Rejected because they are
  guarded as develop-only and the production resource envelope has not been validated.
- **Deploy only the old API image with no changes:** Safe for current data but does not deliver the
  tested upload/compatibility work; retained as the rollback target.
- **Blindly move the validated develop volume back to production:** Rejected because it can erase
  production writes, carries the wrong Pod/volume identity and secrets, and does not provide a
  safe reconciliation path.
- **Restore production into develop and rehearse there:** Recommended as Phase 0 because it gives
  production-shaped evidence without mutating production.
- **Perform a direct in-place table rewrite:** Rejected because it increases lock, WAL, and
  rollback risk and removes the recoverable old-table boundary.
- **Use zero-downtime dual writes/CDC for the first production cutover:** Deferred; it materially
  expands the design and has not been implemented or tested.

## Test plan

### Before production deployment

- Run the focused identity, upload, migration, and API tests plus full backend pytest/mypy in CI.
- Build the candidate image once and record its commit tag and digest.
- Rehearse the migration/seed path on a disposable PostgreSQL/PostGIS database containing a
  production-shaped copy, including interruption and restart.
- Verify the production backup by restoring it to a disposable database and comparing row counts,
  ID bounds, sequences, and representative records.

### Phase 1 canary and smoke tests

- Confirm both Pods are `AVAILABLE` and the API serves OpenAPI/health endpoints.
- Verify campaign, station, sensor, measurement-list, measurement-by-ID, and note routes.
- Verify duplicate semantics with a canary dataset isolated from existing production data.
- Compare query medians and p95s with the captured production baseline; the initial default gate
  is no more than 2x baseline with no new 5xx responses. **[ASSUMPTION — confirm]:** The operator
  accepts this relative latency gate.
- Verify measurement, identity (if enabled), note, and sequence invariants after the canary.

### Phase 0 staging-rehearsal checks

- Compare restored develop counts and ID bounds with the production backup manifest.
- Verify the identity seed is resumable and reaches exact measurement/identity parity.
- Verify the partitioned shadow has exact row/ID coverage before cutover.
- Stop and restart the rehearsal at each durable cursor; confirm no duplicate or orphan rows.
- Re-run the production API baseline queries against the restored/cutover develop database.
- Prove rollback returns the restored develop target to the pre-cutover row, ID, and note counts.

### Phase 2 validation

- Compare source/shadow row counts, distinct IDs, min/max IDs, sensor relationships, duplicate
  constraints, notes, checksums/samples, and partition distribution.
- Test rollback before and after cutover while the old table is retained.
- Capture memory, WAL, disk, duration, restart, and API query metrics.

## Documentation plan

- Update the backend README with the production compatibility mode, migration guardrails,
  maintenance-window requirements, and backup/rollback commands.
- Add the production deployment target and approval gates to the CI/CD documentation.
- Update the Upstream API service page with the production Pods, migration state, and operational
  checks.
- Keep the partition prototype explicitly marked develop-only until Phase 2 is separately approved.

## Rollout/rollback plan

### Rollout gates

1. Requirements and this plan reviewed by the operator.
2. Production compatibility design approved and implemented.
3. CI tests, image build, backup restore rehearsal, and dry-run deployment validation pass.
4. Production database backup/snapshot is verified and the maintenance window is scheduled.
5. Phase 1 API rollout is explicitly approved as an external production write.
6. Post-deploy smoke tests and query benchmarks pass.
7. Phase 2 remains separately gated; it cannot be inferred from Phase 1 success.

### Phase 1 rollback

- If the API image fails health checks or query smoke tests, restore the previous
  `sha-5c974d4` image and restart only the API Pod.
- If an additive migration causes a compatibility issue, stop writes, preserve the backup, and
  use a rehearsed forward-fix or verified restore procedure. Do not improvise an Alembic downgrade
  after production data writes, and do not drop production tables as an emergency action.
- If data invariants change, keep the API offline, preserve logs and the database volume, and
  restore the verified backup only after confirming the exact restore target and outage impact.

### Phase 2 rollback

- Before cutover: discard or retain the shadow table and resume the old live table.
- After cutover but before old-table removal: quiesce writes, reverse the table target, restore
  foreign keys/triggers as tested, and validate counts and notes.
- After old-table removal: use the verified database backup/volume restore; this is not an
  automatic transaction rollback.

## Open questions

- Is the requested rollout limited to Phase 1 compatibility/API deployment, or should it also
  include a production partitioned-storage cutover? Recommended default: Phase 1 only.
- What maintenance window and maximum API downtime are acceptable?
- What production backup mechanism and restore owner will be used for `mobilesniffervolume`?
- Should production Postgres memory and volume capacity be increased before any Phase 2 rehearsal?
- What isolated campaign/station/sensor is approved for a production canary write?
- Should Phase 0 use a new temporary develop volume, or is wiping the current disposable develop
  volume explicitly approved after its benchmark evidence is archived?
- Does Tapis provide an approved volume snapshot/clone workflow, or should the rehearsal use
  `pg_dump`/`pg_restore` plus separately managed globals?
- Should the long sensor-statistics and geometry work be moved to the durable async worker path
  before production full-file uploads are enabled?
- Is the 2x warm-query latency gate acceptable, or should the operator set fixed p95 targets?

## Decisions

### 2026-10-09 — Separate production API rollout from partition cutover

- **Decision:** Plan production in two separately approved phases; the first phase keeps the live
  unpartitioned measurements table and does not enable the partitioned backfill path.
- **Reason:** Production currently has no identity table, only 45 GB reported free, and a 6 GB
  Postgres memory limit. The current develop-only cutover evidence is not sufficient to authorize
  an irreversible production schema/data migration.
- **Alternatives rejected:** Directly promoting the develop partition image and running the
  develop cutover helper in production.
- **User feedback:** The user asked to plan a rollout for `mobilesnifferpostgres` and
  `mobilesnifferapi`; explicit phase scope is still open.
- **Impact on implementation:** Add a production-safe compatibility mode and gated deployment
  workflow before any production image update; keep Phase 2 out of the first release.

### 2026-10-09 — Do not deploy the current image unchanged

- **Decision:** Treat the current `2a1b240` image as not directly deployable to production.
- **Reason:** Its identity migration creates an empty `measurement_identity` table, while the
  application ID lookup path reads through that table. Production currently has no such table and
  no seeded identity rows.
- **Alternatives rejected:** Relying on startup Alembic plus a later manual seed; the API could
  serve requests in the unsafe interval and existing ID lookups could fail.
- **User feedback:** None yet.
- **Impact on implementation:** Add a tested production sequencing/compatibility mechanism and
  make the seed/trigger transition atomic with respect to API availability.

### 2026-10-09 — Use develop as a production-shaped rehearsal, not a volume swap

- **Decision:** Add a staging phase that restores verified production data into an isolated develop
  target, applies and validates the newest design there, and rehearses rollback before production.
- **Reason:** This tests the real production row counts, schema, IDs, and query behavior without
  exposing the live production volume to an unvalidated migration.
- **Alternatives rejected:** Moving the develop volume directly back to production; that could
  erase production writes and carries the wrong volume identity, credentials, and operational
  state.
- **User feedback:** The user proposed using develop to port the entire production Postgres,
  update it to the newest design, and move it back.
- **Impact on implementation:** Add backup/restore rehearsal tooling and a production runbook;
  require the production migration to be repeated against a fresh production snapshot rather than
  blindly swapping volumes.

### 2026-10-09 — Complete production-shaped develop rehearsal in isolated Pods

- **Decision:** Use new disposable develop Pods for the full production restore and migration
  rehearsal; preserve the existing develop load-test database and API.
- **Evidence:** Production counts and ID bounds matched after restore; identity seed and 16-way
  shadow preparation completed; cutover retained the legacy table; post-cutover API smoke tests
  and benchmarks passed.
- **Deviation:** Tapis Files rejected creation of the new backup directory. The user explicitly
  approved retaining the verified logical dump locally for this rehearsal.
- **Impact:** The production backup/restore owner and Tapis Files write path remain open before
  any production migration. The local dump is a temporary rehearsal artifact, not a production
  backup policy.

### 2026-10-09 — Rollback rehearsal passed

- **Decision:** Exercise the guarded rollback before treating the cutover rehearsal as complete.
- **Evidence:** The API restart returned the original `measurements` table to live use, retained
  the partitioned copy under `measurements_partitioned_failed_20261006`, preserved all 10,025,920
  identity rows and the notes foreign key, and passed an authenticated API read.
- **Impact:** The rollback boundary is demonstrated on the isolated develop target. Production
  still requires its own backup, maintenance window, and separately approved migration.

### 2026-10-09 — Preserve legacy lookups during identity migration

- **Decision:** During the Phase 1 compatibility window, measurement ID reads and deletes prefer
  `measurement_identity` when it is populated, but fall back to the legacy measurements table when
  the registry is empty or the identity table is not yet available. Sensor cleanup treats the
  identity table as optional, and measurement-note listing joins the legacy measurements table.
- **Reason:** Alembic intentionally defers the historical identity seed. The API must remain able
  to serve the existing unpartitioned production data while that additive migration is absent,
  empty, or awaiting a separately approved seed/cutover.
- **Alternatives rejected:** Deploying the current identity-dependent lookup path unchanged, or
  making startup synchronously seed all historical measurements before serving requests.
- **User feedback:** The user authorized continuing after the production-shaped develop rehearsal;
  implementation was limited to this compatibility behavior and its tests.
- **Impact on implementation:** No public routes or production schema/cutover commands changed.
  The candidate still requires CI image build and a separately approved production canary before
  any external deployment.

## User feedback / decisions

- 2026-10-09: User requested a rollout plan for the production `mobilesnifferpostgres` and
  `mobilesnifferapi` Pods.
- 2026-10-09: User has not yet selected Phase 1-only rollout versus Phase 1 plus production
  partition cutover.
- 2026-10-09: User proposed using develop as a production-shaped staging target before the
  production rollout; the plan now treats this as Phase 0 and rejects a blind volume swap.
