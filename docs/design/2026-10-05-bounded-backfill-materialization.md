# Bounded Backfill Materialization

Status: Implemented

## Objective

Reduce PostgreSQL peak memory during opt-in historical backfill materialization while
preserving the existing isolated raw-table, deduplicated shadow-table, validation, merge,
and rollback workflow.

## User need

The first real develop benchmark staged a 5,000-row historical slice containing 3.88 million
candidate sensor values and reached the 10 GiB PostgreSQL cgroup ceiling during global JSONB
expansion and deduplication. The historical file must not be attempted again until materialization
has a bounded working set and can resume safely after interruption.

## Current code/system summary

The backfill worker stores wide CSV rows as JSONB in an import-scoped raw table. Materialization
currently expands every sensor value in one SQL statement, performs one global `DISTINCT ON`
over `(sensorid, collectiontime)`, inserts the deduplicated rows into a shadow table, and builds
one unique index. The merge then inserts shadow rows into `measurements` in cursor-bounded
transactions under a station advisory lock.

## Proposed design

1. Add `BULK_BACKFILL_MATERIALIZE_BUCKETS`, defaulting to 64 and bounded by configuration
   validation.
2. Assign each sensor id deterministically to one bucket using modulo arithmetic. Process one
   bucket at a time with the same `DISTINCT ON` source ordering as the current global query.
3. Commit after each bucket and persist the next bucket in `upload_import_backfills`.
4. Heartbeat the import lease between bucket commits so a long historical import remains owned
   by the worker.
5. Build the shadow unique index once after all buckets finish, then run the existing validation,
   mark the state ready, and drop the raw JSONB table.
6. On retry, resume from the persisted bucket cursor. A failed bucket transaction is rolled back;
   a completed bucket is not repeated. Rollback remains available through post-processing start.

The modulo partition is disjoint by sensor id, so duplicates for the same `(sensorid,
collectiontime)` cannot cross bucket boundaries. Within each bucket, the existing first-source
ordering remains authoritative.

## Files likely affected

- `app/core/config.py`
- `app/db/models/upload_import_backfill.py`
- `app/services/upload_import_backfill_service.py`
- `alembic/versions/20261005_bounded_backfill_materialization.py`
- `tests/test_upload_import_backfill.py`
- `README.md`

## API/schema changes

No public endpoint or response shape changes. Add one nullable-free, default-zero durable state
column, `upload_import_backfills.materialize_cursor`, and one internal environment setting.

## Data flow

```text
raw JSONB rows
      |
      +--> sensor bucket 0 --> DISTINCT ON --> shadow table --+
      +--> sensor bucket 1 --> DISTINCT ON --> shadow table   |
      +--> ...                                                +--> unique index --> validate
      +--> sensor bucket N --> DISTINCT ON --> shadow table --+       |
                                                                       +--> bounded live merge
```

Each bucket transaction advances the durable cursor only after its insert succeeds. The worker
can resume from the next bucket after a lease loss or process restart.

## Risks and tradeoffs

- More SQL statements and commits may reduce throughput compared with one global query.
- The shadow table still grows to the full deduplicated import size; this change bounds query
  working memory, not total disk usage.
- The final unique-index build and collision validation remain resource-sensitive and must be
  measured on develop.
- A misconfigured bucket count can trade memory for runtime; the default is intentionally
  conservative and can be adjusted only on disposable develop runs first.

## Alternatives considered

- Keep the single global materialization query: rejected because the real benchmark reached the
  database memory ceiling.
- Build the unique shadow index before every insert: rejected because it increases per-row index
  maintenance and WAL pressure, contrary to the original optimization goal.
- Partition the live `measurements` table: deferred because the current table is not partitioned
  and that would require a broader migration and attach/concurrency design.
- Use a single raw-row cursor without sensor bucketing: rejected because duplicates can span raw
  row batches, changing first-source semantics or requiring a second global deduplication pass.

## Test plan

- Unit-test modulo bucket assignment and configuration bounds.
- Run the focused backfill test module and the full backend test suite.
- Run changed-module mypy and diff checks.
- Deploy through the existing develop CI path only after code/test review.
- Run a disposable 500-1,000-row real-data develop benchmark with both bulk flags enabled only
  for the test, collecting memory, WAL, row counts, phase transitions, rollback, and residue.
- Do not run the full historical file until the bounded benchmark stays below the configured
  memory safety margin and cleanup is verified.

## Documentation plan

Update the backend README with the bucket setting, resumability behavior, and the develop-only
benchmark gate. The DSO architecture service page should be synchronized when the separate docs
repository is next updated.

## Rollout/rollback plan

The new setting is inactive unless backfill is explicitly enabled. Deploy the additive migration
and code to develop, keep both flags false by default, and enable them only for a disposable
benchmark. If the benchmark is unsafe, disable the flags, stop the worker, invoke the supported
backfill rollback endpoint while post-processing is pending, and remove disposable campaign and
import bookkeeping after verifying zero residue. Revert the application commit and migration
only if the code itself is faulty; the migration is additive and does not alter live measurement
rows.

## Open questions

- What memory margin below the 10 GiB cgroup limit should be required before a larger slice is
  approved? Proposed gate: keep peak below 8 GiB and record zero OOM events.
- Is the resulting runtime acceptable at 64 buckets, or should develop use 128 after the first
  bounded benchmark?

## Decisions

### 2026-10-05 - Bound materialization by disjoint sensor buckets

- **Decision:** Process deterministic sensor-id buckets with a persisted resume cursor and build
  the unique shadow index once after all buckets complete.
- **Reason:** The single global expansion reached the 10 GiB develop database memory ceiling;
  sensor-id buckets preserve deduplication semantics while bounding sort working sets.
- **Alternatives rejected:** Global expansion, per-row indexed insertion, live-table partitioning,
  and raw-row-only batching for the reasons above.
- **User feedback:** The user said “ok keep going” after the safety-stopped develop benchmark;
  this authorizes continuing with the bounded optimization and its disposable develop test.
- **Impact on implementation:** Add one state column, one setting, one additive migration, bucketed
  resumable SQL, focused tests, and README guidance.

## User feedback / decisions

- 2026-10-05: User requested that work continue after the real-data benchmark was safely stopped.
- 2026-10-06: Implemented as specified. The only deviation is that the focused unit tests cover
  predicate parameterization and configuration bounds; real bucket/resume semantics remain a
  develop integration-test gate because the local suite has no PostgreSQL/PostGIS fixture.
- 2026-10-06: The develop integration gate passed with a disposable 1,000-row real-data slice:
  776,000 values staged/materialized/merged/inserted, post-processing completed, zero collisions,
  zero OOM events, and exact cleanup verified. The full historical file remains out of scope until
  additional capacity and throughput evidence is collected.
