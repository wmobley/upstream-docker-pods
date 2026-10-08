# Partitioned Measurements with Global Measurement Identity

Status: Implementing

## Objective

Evaluate and, after approval, migrate the measurements storage path to a sensor-partitioned
table while preserving globally unique `measurementid` values, existing measurement lookup
URLs, note references, duplicate handling, and rollback safety.

## User need

**Primary user:** The service operator running large historical imports and maintaining the
develop deployment.

**Secondary users:** API clients and data users who retrieve measurements or attach notes by
`measurementid`.

**Job-to-be-done:** Load historical measurements without exhausting the PostgreSQL memory
limit, while keeping existing measurement IDs and lookup behavior stable.

**Current pain:** The unpartitioned measurements table and its indexes/page cache grow together
during large imports. Column splitting reduces per-operation pressure but cumulative table and
index pressure still reaches the develop safety margin.

**Definition of success:** A develop-only migration prototype can represent the existing data,
preserve ID-based note references, keep `(sensorid, collectiontime)` duplicate semantics, and
support safe cutover/rollback without data loss or an API contract change.

## Current code/system summary

- `measurements.measurementid` is the database primary key and is omitted from normal insert
  statements so PostgreSQL supplies it.
- `sensorid` is a foreign key to `sensors.sensorid`; current import deduplication and conflict
  handling use `(sensorid, collectiontime)`.
- `notes.measurement_id` directly references `measurements.measurementid`.
- Measurement writes exist in the ORM repository, the regular CSV upload utility, and the bulk
  backfill merge path.
- Measurement reads and updates commonly address a measurement by `measurementid` alone.
- PostgreSQL permits a partitioned table's unique constraints only when they include the
  partition key. Therefore a table partitioned by `sensorid` cannot declare
  `PRIMARY KEY (measurementid)` directly.
- A disposable develop probe validated that a non-partitioned identity table can own
  `PRIMARY KEY (measurementid)`, while a sensor-hash-partitioned measurements table uses
  `UNIQUE (measurementid, sensorid)` and `UNIQUE (sensorid, collectiontime)`.

## Proposed design

Add a small non-partitioned identity table:

```sql
measurement_identity(
    measurementid INTEGER PRIMARY KEY,
    sensorid INTEGER NOT NULL REFERENCES sensors(sensorid)
)
```

Create the replacement measurements table partitioned by hash of `sensorid`. It retains the
existing measurement columns and adds:

- a foreign key from `measurementid` to `measurement_identity.measurementid`;
- a parent-level unique constraint on `(measurementid, sensorid)`;
- the existing unique constraint on `(sensorid, collectiontime)`;
- the same sensor and upload-event foreign-key behavior.

Change `notes.measurement_id` to reference the identity table. The public field remains an
integer measurement ID; no API caller needs to provide `sensorid` to resolve a note.

Use a database-side canonical measurement-ID registration path. Existing IDs are copied into the
identity table by the guarded seed phase before the cutover. An `AFTER INSERT` trigger on the
live/replacement measurements table registers each `(measurementid, sensorid)` transactionally,
so duplicate-skipped measurement rows cannot leave orphan identities. The measurement-to-identity
foreign key is deferred until transaction commit, allowing the trigger to satisfy it while
preserving referential integrity. This keeps the ORM, legacy CSV, bulk SQL, and backfill writers
on one allocation path without four separate application-level ID implementations.

The migration should be phased:

1. Add the identity table and validate that existing `measurementid` values are unique and
   non-null.
2. Seed identity rows from existing measurements with a guarded, resumable helper that commits
   bounded batches, then validate counts, sensor relationships, and the sequence high-water mark.
3. Build and validate a partitioned shadow measurements table, including all indexes and
   foreign keys.
4. Add the identity-registration trigger to every live/replacement measurement table and update
   the note relationship to use the identity table.
5. Perform a controlled cutover under an explicit measurement-write lock/quiescence policy.
6. Keep the old table available through a soak period before any destructive removal.

**[ASSUMPTION — confirm]:** The first real develop migration will use a maintenance window that
pauses measurement writes during final catch-up and table renaming. A production design that
requires zero write downtime would need a separate dual-write/CDC phase and is not included in
this first implementation.

## Files likely affected

- `app/db/models/measurement.py`
- `app/db/models/measurement_identity.py`
- `app/db/models/note.py`
- `app/db/repositories/measurement_repository.py`
- `app/db/repositories/note_repository.py`
- `app/utils/upload_csv.py`
- `app/services/upload_import_backfill_service.py`
- measurement-related API/query code and tests
- new Alembic migration(s) under `alembic/versions/`
- new focused migration/identity/partition tests
- `docs/design/2026-10-06-partitioned-measurements-identity-table.md`
- backend README and service documentation if rollout becomes supported behavior

## API/schema changes

Database changes:

- Add `measurement_identity` with globally unique `measurementid`.
- Replace the unpartitioned measurements storage with sensor-hash partitions.
- Move the notes foreign key target from `measurements` to `measurement_identity`.
- Add a database trigger/function used by all measurement writers to register generated IDs.

API changes:

- No intended route or response-shape changes.
- Measurement IDs remain the identifiers used by measurement and note endpoints.
- Existing measurements retain their `sensorid`; update requests cannot move a measurement to a
  different sensor because `sensorid` is the partition key and part of the ORM identity.

The SQLAlchemy mapping must be reviewed carefully because the database uniqueness guarantee for
the partitioned table is composite while existing application lookups are ID-only. The identity
table is the authoritative ID-only key; the ORM mapping and repository joins must not introduce
duplicate or ambiguous rows.

## Data flow

```text
measurement writer
       |
       +--> allocate/register measurementid in identity table
       |
       +--> insert measurement into sensor hash partition
                    |
                    +--> unique (sensorid, collectiontime)

notes.measurement_id --> measurement_identity.measurementid
```

Migration flow:

```text
existing measurements
        |
        +--> seed measurement_identity
        |
        +--> copy to partitioned shadow table
        |
        +--> validate counts, IDs, FKs, indexes, and query results
        |
        +--> quiesce writes --> final catch-up --> atomic rename/cutover
```

## Risks and tradeoffs

- The cutover is a schema/data migration, not merely an index optimization.
- The trigger/function becomes part of the measurement write contract; disabling or bypassing it
  can create orphaned rows or sequence collisions.
- A global identity table adds one extra write/index lookup per new measurement.
- ID-only ORM identity semantics need explicit tests because the physical measurements table has
  a composite uniqueness constraint.
- Existing foreign-key cascade behavior must be reproduced deliberately when moving notes to the
  identity table; deleting an identity row must not leave a measurement row behind.
- Rebuilding the historical table requires substantial disk, WAL, and temporary index space even
  if peak working memory is lower.
- A maintenance window is operationally simpler but temporarily pauses measurement writes.
- Rollback after destructive removal of the old table is not instant; the old table must remain
  until validation and soak checks finish.

## Alternatives considered

- Keep the unpartitioned measurements table and only split files: already tested; it reduces
  individual working sets but does not remove cumulative final-table/index/page-cache pressure.
- Partition by `measurementid`: preserves a single-column primary key, but weakens locality for
  the sensor/time access pattern and complicates global `(sensorid, collectiontime)` uniqueness.
- Add `sensorid` to `notes` and use a composite note foreign key: technically possible, but it
  changes the notes schema and API/query contract unnecessarily.
- Use triggers or application conventions without an identity table: rejected because ID-only
  uniqueness would not be represented by a database-enforced key visible to foreign keys.
- Keep notes pointing at the partitioned table: rejected because PostgreSQL cannot use the
  sensor-partitioned table as an ID-only referenced key.

## Test plan

- Migration tests on real PostGIS/PostgreSQL, not SQLite-only fixtures.
- Validate identity seeding: row count, min/max IDs, duplicate detection, sensor references, and
  sequence high-water mark.
- Validate all measurement writers allocate IDs and insert atomically.
- Validate `(sensorid, collectiontime)` duplicate behavior and first-source semantics.
- Validate measurement reads, updates, deletes, exports, station deletes, and note joins by ID.
- Validate foreign-key cascades for sensor, measurement identity, upload event, and notes paths.
- Run a shadow copy of representative develop data and compare row counts/checksums/query samples.
- Exercise interruption before cutover, during catch-up, and after cutover.
- Exercise rollback while the old table is retained and verify no orphaned IDs or notes.
- Run the existing focused suite, full backend pytest, mypy, and deployment health checks.
- Run a real-data develop backfill benchmark with memory, WAL, runtime, and cleanup telemetry.

## Documentation plan

Document the identity table, partitioning key, ID allocation rule, maintenance-window
requirements, rollback boundary, and operational checks in the backend README and the relevant
DSO architecture service page after implementation is approved.

## Rollout/rollback plan

Develop rollout:

1. Keep the current unpartitioned table as the live source.
2. Apply additive identity/schema changes only.
3. Seed and validate identity rows.
4. Build the partitioned shadow table and compare it with live data.
5. Deploy writer changes while still targeting the current table, or keep a compatibility path,
   until the new allocation behavior is proven.
6. Pause measurement writes, acquire the migration advisory lock, catch up, validate, and cut over.
7. Keep the old table under a recovery name through the soak period.

Rollback before destructive removal: pause writes, reverse the table target, restore the prior
foreign-key target if needed, and leave the identity table in place until orphan checks pass.

Rollback after old-table removal requires a database snapshot/backup restore or a reverse copy;
it is not treated as an automatic transaction rollback.

## Open questions

- Should the initial implementation require a maintenance window, or is zero-downtime dual-write
  required from the start?
- Should `measurement_identity` retain `sensorid`, or should it contain only the ID and rely on
  the measurement row for sensor ownership?
- Should the allocator be a database function, a sequence-plus-insert helper, or an application
  repository operation?
- What soak duration and validation evidence are required before retiring the old table?
- Should the identity table use `INTEGER` to match the existing API type, or should this migration
  intentionally widen IDs to `BIGINT`?

## Decisions

### 2026-10-06 — Approve develop-only implementation with maintenance-window cutover

- **Decision:** Implement the identity-table and sensor-partitioned measurements design for
  develop first, using a maintenance window for the initial cutover.
- **Reason:** The disposable prototype passed, and a quiesced cutover provides a bounded,
  reversible first implementation without introducing dual-write/CDC complexity.
- **Alternatives rejected:** Production rollout and zero-downtime dual writes are deferred until
  develop migration, performance, and rollback evidence exists.
- **User feedback:** The user said “ok do it” after confirming the work remains develop-only.
- **Impact on implementation:** Implement the migration, writer updates, focused tests, and
  develop validation; do not deploy to production or remove the old table during this phase.

### 2026-10-06 — Use a database trigger for identity registration

- **Decision:** Register generated measurement IDs with a transactional database trigger rather
  than duplicating allocation logic in each application writer.
- **Reason:** Four existing insert paths already rely on the database-generated measurement ID;
  one database-side path preserves their behavior and makes the partitioned replacement
  compatible with legacy and bulk writers.
- **Alternatives rejected:** Rewriting each writer independently would increase divergence and
  leave future SQL writers at risk of bypassing identity registration.
- **User feedback:** The user approved proceeding after the develop-only prototype passed.
- **Impact on implementation:** Add an additive identity migration and trigger/function first;
  attach the same trigger to the partitioned replacement during the later cutover.

### 2026-10-06 - Validate identity-table architecture before real schema changes

- **Decision:** Use a disposable identity-table plus sensor-partitioned-measurements prototype
  before changing application tables.
- **Reason:** The prototype confirmed that globally unique ID references, notes foreign keys,
  and sensor-local uniqueness can coexist under PostgreSQL's partitioning rules.
- **Result:** 388,000 identities, 388,000 partitioned measurements, two note references, and
  both uniqueness indexes succeeded; all probe tables were removed afterward.

### 2026-10-06 — Defer the historical identity seed out of Alembic startup

- **Decision:** Keep the Alembic migration additive: create the empty identity table and trigger
  function, then seed existing measurements with a guarded, resumable develop helper and install
  the live trigger only after validation succeeds.
- **Reason:** The first develop deployment attempted to seed all 64,431,777 measurements in one
  migration transaction and reached the PostgreSQL cgroup memory ceiling while checkpoints and
  WAL accumulated. The deployment was stopped before OOM and the migration rolled back cleanly.
- **Alternatives rejected:** Repeating the automatic one-shot seed was rejected because API
  startup would remain coupled to an unbounded data operation; a smaller batch inside Alembic
  would still make startup non-resumable and difficult to stop safely.
- **User feedback:** The user asked to deploy and check the develop implementation; develop-only
  scope and the explicit maintenance-window workflow remain approved.
- **Impact on implementation:** Add `scripts/seed_measurement_identity_develop.py`, update the
  migration regression tests and README, and require the seed validation to pass before running
  the partition prepare/cutover helper.

### 2026-10-06 — Make partition preparation resumable after the full-copy failure

- **Decision:** Replace the single long `INSERT ... SELECT` prepare operation with durable,
  sensor-hash-partitioned copy steps that commit independently and resume from a partition cursor.
- **Reason:** The first real develop prepare attempt against approximately 69 million rows lost
  its remote execution connection before recording `prepared`; it left only an empty shadow shell,
  which was removed without changing the live table. A single operation is too fragile for this
  table size and memory limit.
- **Alternatives rejected:** Re-running the unchanged helper was rejected because it repeats the
  same unbounded operation and provides no safe resume point. Cutting over after a partial copy was
  rejected because source/shadow validation had not completed.
- **User feedback:** The user approved trying the partitioned approach again after the failed
  prepare and recovery.
- **Impact on implementation:** Extend the develop helper's migration state with a copy/index
  cursor, commit each partition step, add focused tests for cursor progression and partition
  routing, and keep cutover gated on complete validation.

### 2026-10-06 — Delegate copy routing to PostgreSQL's partition predicate

- **Decision:** Use PostgreSQL's `satisfies_hash_partition()` function against the shadow
  table's `regclass` when selecting each source partition.
- **Reason:** A develop probe showed that a raw `hashint4(sensorid) % 16` expression does not
  necessarily match PostgreSQL's partition routing; sensor `8704` was selected for remainder 0
  by the raw expression but belongs to remainder 8 according to the actual partition bound.
- **Impact on implementation:** The copy step now uses the server's own partition-routing logic,
  eliminating a silent misrouting risk and making the check directly testable against the shadow
  table definition.

### 2026-10-08 — Hold cutover pending ID-lookup compatibility work

- **Decision:** Keep the prepared shadow table out of service until application ID-only lookup
  paths and the notes foreign key are updated and benchmarked.
- **Evidence:** Develop benchmarks showed sensor/time lookup at approximately 3.2 ms on the
  shadow versus 3.1 ms on the live table, but the identity-join measurement-ID lookup took
  approximately 824 ms to plan and 53 ms to execute versus approximately 0.08 ms on the live
  primary-key lookup. The current ORM still maps `Measurement.measurementid` as a direct primary
  key and `Note.measurement_id` to `measurements.measurementid`.
- **Impact:** The shadow remains prepared and validated, but no rename, foreign-key cutover, or
  writer restart against the partitioned table is authorized by this benchmark. The next change
  must provide an efficient ID lookup strategy and update the affected ORM/repository paths before
  another cutover decision.

### 2026-10-08 — Add application compatibility for the prepared partition

- **Decision:** Add a `MeasurementIdentity` ORM model, map `Measurement` with the composite
  `(measurementid, sensorid)` identity, resolve ID-only measurement reads through the identity
  table, and move note joins/FK metadata to the identity table.
- **Reason:** The partitioned table can only enforce uniqueness with the partition key included;
  an ID-only lookup must first resolve the sensor so PostgreSQL can prune to one child partition.
- **Safety rule:** Treat `sensorid` as immutable for existing measurements. Allowing it to change
  would move the row's partition without changing the canonical identity mapping.
- **Validation:** The focused compatibility tests and full backend suite pass locally; the
  develop deployment and post-deploy lookup benchmark remain outstanding before cutover.

### 2026-10-08 — Register identities after successful measurement inserts

- **Decision:** Use an `AFTER INSERT` identity trigger with a deferred measurement-to-identity
  foreign key, and recreate the bulk staging table on every pooled connection used for a batch.
- **Reason:** The develop full-file benchmark exposed two correctness failures: a before-insert
  trigger registered IDs for rows later skipped by `ON CONFLICT`, and the bulk importer lost its
  connection-local temporary table after a commit. The fixes preserve identity/measurement parity
  and make bounded bulk batches safe across SQLAlchemy pool checkouts.
- **Alternatives rejected:** Keeping the before-insert trigger would require accepting orphan
  identities or redesigning duplicate handling; dropping the foreign key would weaken integrity.
- **Validation:** Focused bulk-upload tests pass locally; the develop full-file rerun is pending
  deployment of this fix.

## User feedback / decisions

- 2026-10-06: User approved trying the identity-table design after clarifying that measurement
  IDs are globally unique and sensor-based for lookup.
- 2026-10-06: The draft was approved for develop-only implementation with the maintenance-window
  approach; the zero-downtime alternative remains deferred.
- 2026-10-06: User approved develop-only implementation with the maintenance-window approach.
- 2026-10-06: Develop invariant checks found 64,431,777 measurements, no null IDs/sensors, no
  duplicate IDs, and an existing integer sequence ahead of the current maximum; retain INTEGER
  for the first migration rather than widening the API type.
- 2026-10-08: Application compatibility was implemented and validated locally; deploy and
  benchmark it on develop before deciding whether the prepared shadow is ready for cutover.
- 2026-10-08: The develop full-file test was explicitly approved. Legacy mode measured 1,552,000
  values from 2,000 source rows in 12m29s, so the full legacy run was stopped as impractical;
  the set-based bulk mode was selected for the full-file test after fixing the trigger and
  temporary-table defects.
