# Independent Location for Measurement Notes

**Status:** Implemented

---

## Objective

Let a measurement note carry its own point location, independent of the measurement it's attached to, so a user can annotate something spatially offset from where the sensor took the reading (e.g. "plume traced back to this location") while still seeing both points together for context.

---

## User need

**Primary users:** Field researchers and data analysts reviewing sensor time series who want to record where a phenomenon *actually* originated or was observed, not just where the instrument happened to be.

**Job-to-be-done:** While looking at a measurement (e.g. an elevated reading on the chart), mark a second location — a plume source, a visible disturbance, an upstream cause — and keep that annotation attached to the note for future reference.

**Current pain:** The map preview added to the measurement-note callout (2026-07-22) only shows the measurement's own fixed coordinate. There's no way to record "this reading came from over there."

**Definition of success:**
- Adding a measurement note optionally includes picking a point on a map.
- The note callout shows both the measurement's location and the note's own location together, visually distinct.
- Existing notes without a location continue to work unchanged (fully optional field).

---

## Current code/system summary

- `Note` model (`app/db/models/note.py`) has no geometry column at all — only FKs to campaign/station/sensor/measurement, `content`, `created_by`, `created_at`.
- `NoteCreate`/`NoteUpdate`/`NoteItem` (`app/api/v1/schemas/note.py`) are plain content-only schemas, shared across all four note scopes (campaign/station/sensor/measurement) via the same `NoteService`/`NoteRepository`.
- Measurements already have an established WKT-in / GeoJSON-out geometry pattern worth reusing exactly:
  - Input: `MeasurementIn.geometry: Optional[str]` — a WKT string (`"POINT(lon lat)"`), converted server-side via `WKTElement(request.geometry, srid=4326)` before persisting (`measurement_repository.py`).
  - Output: `MeasurementItem.geometry: Point` where `Point` is from `geojson_pydantic` (`from geojson_pydantic import Point`), populated via `func.ST_AsGeoJSON(...)` in bulk list queries.
- Frontend: `MeasurementItem.geometry` (SDK-generated from the same schema) already flows into the chart's `DataPoint`/`ProcessedDataPoint` and, as of 2026-07-22, into `MeasurementNoteCallout`'s `SelectedPointPayload.geometry`, which renders a single, read-only `GeometryMap` showing the measurement's point.
- `GeometryMap` (`src/app/common/GeometryMap/GeometryMap.tsx`) is read-only today: it renders exactly one `GeoJSON.Geometry` as a single feature, computes bounds/zoom from it, no marker layer, no click handling. It's shared by four other call sites — campaign coverage map (`CampaignDashboard.tsx`), station coverage map (`StatsSection.tsx`), scatter-chart tooltip (`ScatterTimeSeriesChart.tsx`), and the campaign card map on the home page (`CampaignCard.tsx`) — all of which must keep working unchanged.
- Auth: measurement note create/update already requires `get_edit_user`; only the note's own author can edit/delete it (`note_service.py` checks `created_by == username`). No change needed here — location just rides along with content.

---

## Proposed design

### Scope (per user decision, 2026-07-23)
- **Geometry type:** point only (no lines/polygons in this iteration).
- **Note scopes:** measurement notes only. The DB column is added generically to `Note` (so campaign/station/sensor notes could adopt it later without another migration), but only the measurement-note request schemas expose a `location` field at all — see API schema changes below for why this is enforced at the schema layer, not just at runtime.
- **Display:** both the measurement's own location and the note's custom location are shown together on the same small map, visually distinct (different marker colors/icons).

### Data model

Add one nullable column to `Note`:

```python
location: Mapped[Optional[Geometry]] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
```

Alembic migration: `add_location_to_notes` — additive, nullable, no backfill, no impact on existing rows or the three non-measurement note scopes.

### API schema changes

Mirror the existing measurement geometry pattern for representation, but — per architect review — enforce the scope restriction at the **schema layer**, not with a runtime 400. A shared `NoteCreate`/`NoteUpdate` with a `location` field that only some routes honor would put the field on the generated OpenAPI spec and TypeScript SDK for all four scopes, relying entirely on someone remembering to add a check in every `create_*`/`update` path — exactly the kind of drift a future 5th scope could silently skip. Splitting the schema makes it structurally impossible for the other three routes to even send a location:

- `NoteCreate` / `NoteUpdate` (base, used by campaign/station/sensor routes): **unchanged** — no `location` field exists on these at all.
- New `MeasurementNoteCreate(NoteCreate)` / `MeasurementNoteUpdate(NoteUpdate)`, used only by `campaign_station_sensor_measurement_notes.py`:
  - `location: Optional[str] = None` — WKT string, e.g. `"POINT(-97.7431 30.2672)"`.
  - Clear-vs-omit semantics (resolved — see Decisions): this API's existing `NoteUpdate.content` is already a required field on every PATCH (these endpoints behave as full replacements, not sparse patches — there's no existing partial-update convention to preserve). `MeasurementNoteUpdate.location` follows the same convention: the frontend always sends the full desired state — the existing WKT to keep it, or `null`/omitted to clear it. No `exclude_unset` machinery needed.
- `NoteItem.location: Optional[Point] = None` — stays on the shared response schema (`Point` from `geojson_pydantic`, same type already used for `MeasurementItem.geometry`). Reading is scope-safe regardless of which route created the note, since only measurement notes will ever have a non-null value.

`NoteRepository`:
- `create(..., location: str | None = None)` → `WKTElement(location, srid=4326) if location else None`, same conversion `measurement_repository.py` already uses.
- `update(note_id, content, location: str | None = None)` — always sets `location` to whatever is passed (matching the "full replacement" semantics above); non-measurement callers simply never pass this argument.
- Reading back: use `geoalchemy2.shape.to_shape(note.location)` + `shapely.geometry.mapping(...)` to build a GeoJSON-compatible dict for `Point` validation. **Note this is a deliberate, small departure from the codebase's more common bulk-query idiom** — `measurement_repository.py`/`station_service.py` serialize geometry at the SQL layer via `func.ST_AsGeoJSON(...).label(...)` + `json.loads()`. Per architect review, doing the equivalent for notes would mean restructuring all four `list_by_*` repository methods (three of which will never have a location) to add a label column only one scope uses. Given note lists are small (no pagination-scale concern) and `to_shape`/`mapping()` on an already-loaded ORM object costs no extra DB round-trip, this is an acceptable, explicitly-acknowledged inconsistency rather than silent drift — call it out in a code comment where `_to_item` does the conversion.

`NoteService`:
- `create_measurement_note(...)` gains a `location: str | None = None` param, passed through to the repository.
- `create_campaign_note` / `create_station_note` / `create_sensor_note` signatures are **unchanged** — there is no location parameter to reject, because `NoteCreate` has no such field to receive one.
- `_to_item` converts `note.location` (if present) to `Point` via the shape/mapping conversion above.

Routes affected: only `campaign_station_sensor_measurement_notes.py` imports and uses `MeasurementNoteCreate`/`MeasurementNoteUpdate` and passes `location` through. The other three note route files are untouched.

**Residual risk (acknowledged, not fixed in this iteration):** the schema split prevents the normal API write paths from setting a non-measurement note's location. It does not add a DB-level `CHECK` constraint, so a future bulk-import or direct-DB path that bypasses `NoteService` could still write a location onto a non-measurement note. Given no such path exists today, this is accepted as a documented gap rather than added complexity — flagged here so it isn't forgotten if a bulk note-import feature is ever built.

### Frontend

- Regenerate `packages/upstream-api` from the updated OpenAPI spec (existing `update-upstream-api-client.sh` flow) to pick up `location` on the Note schemas.
- `useCreateMeasurementNote` / `useUpdateNote` (measurement call sites only): accept an optional `location: string` (WKT) alongside `content`.
- `GeometryMap`: extend with new **optional** props so existing read-only call sites are unaffected —
  - `markers?: { position: GeoJSON.Point; color?: string; label?: string }[]` — renders additional `CircleMarker`/`Marker` layers on top of the base geometry.
  - `onPick?: (point: GeoJSON.Point) => void` — when provided, clicking the map places/moves a marker and reports the picked point; used only by the note-creation flow.
  - **Critical fix from skeptic review:** `calculateBounds` currently only traverses the single base `geoJSON` prop's coordinates. Since the entire point of this feature is that a note's location can be meaningfully *offset* from the measurement (a plume traced upstream), an offset marker could render outside the computed viewport — invisible without the user manually panning/zooming, which would defeat "see both points together." `calculateBounds` must be extended to also fold in every `markers[].position` before computing the bounding box and zoom level, not just the base geometry.
- `AddNoteForm` (measurement variant): add an optional "Pick location on map" toggle that renders an interactive `GeometryMap` with `onPick`; the picked point is sent as `location` alongside `content`.
- `MeasurementNoteCallout`: the map preview renders the measurement's point (existing, e.g. blue pin) plus one marker per note that has its own `location` (e.g. orange pin), so the offset between "where it was measured" and "where the note points to" is visible at a glance. Editing a note with `canWrite` reuses the same interactive picker to move/clear its marker.

---

## Files likely affected

### Backend (`upstream-docker-pods`)
| File | Change |
|------|--------|
| `app/db/models/note.py` | add nullable `location` column |
| `alembic/versions/` | new migration: add `location` to `notes` |
| `app/api/v1/schemas/note.py` | add `MeasurementNoteCreate(NoteCreate)`/`MeasurementNoteUpdate(NoteUpdate)` with `location`; add `location` to shared `NoteItem` |
| `app/db/repositories/note_repository.py` | persist WKT on create/update |
| `app/services/note_service.py` | thread `location` through measurement create/update only; convert to `Point` in `_to_item` |
| `app/api/v1/routes/campaigns/campaign_station_sensor_measurement_notes.py` | use `MeasurementNoteCreate`/`MeasurementNoteUpdate`, pass `location` through |

### Frontend (`upstream-ui`)
| File | Change |
|------|--------|
| `packages/upstream-api` | regenerate from updated OpenAPI spec |
| `src/hooks/notes/useNotes.ts`, `types.ts` | optional `location` on measurement create/update |
| `src/app/common/GeometryMap/GeometryMap.tsx` | optional `markers`/`onPick` props (backward compatible) |
| `src/app/common/Notes/AddNoteForm.tsx` | optional location picker (measurement variant) |
| `src/app/LineConfidenceChart/components/MeasurementNoteCallout.tsx` | render measurement pin + per-note pins; picker in edit mode |

---

## API/schema changes

- New nullable DB column (`notes.location`), additive migration, no backfill.
- New `MeasurementNoteCreate`/`MeasurementNoteUpdate` schemas (subclassing `NoteCreate`/`NoteUpdate`), used only by the measurement-notes route, add an optional `location: str | None` field (WKT). Base `NoteCreate`/`NoteUpdate` — used by campaign/station/sensor routes — are unchanged; those routes have no way to receive a location at all.
- `NoteItem` gains an optional `location: Point | None` field (GeoJSON), shared across all scopes for reading (safe, since only measurement notes will ever populate it).
- No breaking changes to existing fields or routes; all changes are additive and optional.
- Known residual gap: no DB-level constraint preventing a non-API write path from setting `location` on a non-measurement note (see API schema changes section for reasoning).

---

## Data flow

```
User clicks "Pick location" in AddNoteForm (measurement note)
  → interactive GeometryMap.onPick fires with {type: "Point", coordinates: [lon, lat]}
  → AddNoteForm converts to WKT "POINT(lon lat)"
  → useCreateMeasurementNote({content, location})
  → POST .../measurements/{id}/notes  {content, location: "POINT(lon lat)"}
  → NoteService.create_measurement_note(...) → NoteRepository.create(..., location=WKTElement(...))
  → stored in notes.location

Reading back:
  → NoteRepository list/get returns ORM Note with `location` as WKBElement (or None)
  → NoteService._to_item: to_shape(note.location) → shapely Point → mapping() → Point(**dict) if location is not None else None
  → NoteItem.location included in ListNotesResponse

Frontend render:
  → MeasurementNoteCallout already has point.geometry (measurement's own location)
  → for each note in notesData.items with note.location, render an additional marker
  → GeometryMap renders base geometry (measurement point) + all note markers together
```

---

## Risks and tradeoffs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `GeometryMap`'s new optional props accidentally change behavior for the 4 existing read-only call sites | Low | Props are opt-in and default to `undefined`; existing call sites pass nothing, keep verifying via typecheck + manual check of campaign/station coverage maps, the scatter tooltip, and the home-page campaign card after the change |
| Offset note marker renders outside the visible map viewport, silently defeating "see both locations together" | Medium (confirmed gap, not hypothetical — `calculateBounds` doesn't look at `markers` today) | Fixed in design: `calculateBounds` must incorporate `markers[].position`, not just the base geometry — see Frontend section |
| Coordinate order mixups (GeoJSON `[lon, lat]` vs. Leaflet `LatLng(lat, lon)` vs. WKT `POINT(lon lat)`) | Medium | Reuse the exact same conversion helpers/pattern already proven for `Measurement.geometry`, don't invent new ones |
| Bloating `GeometryMap` into a kitchen-sink component | Low-medium | Keep `markers`/`onPick` narrowly scoped to what this feature needs; don't add drawing/polygon support now (explicitly out of scope per user decision) |
| A future 5th note scope, or a bulk-import path, bypasses the location restriction | Low (no such path exists today) | Schema split (see API schema changes) makes the restriction structural for all current write paths; documented as a residual gap rather than solved with a DB constraint, since no bypass path exists yet |
| No spatial index on `notes.location` despite the spec citing future "notes near X" queries as a benefit | Low for now | Not needed at current/expected note volume; add an index if/when such a query is actually built, not preemptively |

---

## Alternatives considered

**A. Separate `note_locations` table (one-to-many)**
Would allow multiple locations per note or richer per-location metadata later. Rejected for now — user scoped this to a single point per note; a join table is unwarranted complexity until a real need for multiple points per note shows up.

**B. Store location as lat/lng floats instead of PostGIS geometry**
Simpler column type, no geoalchemy2 conversion needed. Rejected — inconsistent with how every other spatial field in this schema (`Measurement.geometry`, `Station.geometry`, `Campaign.geometry`) is stored; would fragment the spatial data model and lose PostGIS query capability (e.g. future "notes near X" queries) for no real benefit.

**C. Freeform shapes (line/polygon) for plume boundaries**
Explicitly deferred by user decision (2026-07-23) — point-only for this iteration. A polygon/line annotation tool (e.g. Leaflet Draw) is a materially bigger frontend lift and can be layered on later without reworking the point-based column (a `Geometry` column without a hardcoded subtype could hold any shape; today's plan uses `Geometry("POINT", ...)` which would need a follow-up migration to loosen if this is revisited — noting that tradeoff explicitly here rather than over-building now).

---

## Test plan

### Backend
- Unit: `NoteRepository.create`/`update` persist and round-trip a WKT location correctly (matches measurement repository test patterns if any exist).
- Unit: `NoteService._to_item` converts a stored location to the correct GeoJSON `Point` (and returns `None` when absent).
- Unit: measurement-note create/update accepts `location`; campaign/station/sensor-note create/update reject a non-null `location` with `400`.
- Regression: full existing suite (152 tests as of 2026-07-22) must still pass unchanged.

### Frontend
- Manual: `GeometryMap`'s four existing read-only usages (campaign coverage, station coverage, scatter tooltip, home-page campaign card) render unchanged with no `markers`/`onPick` passed.
- Manual: adding a measurement note with a picked location shows both pins in the callout; adding one without a location behaves exactly as today.
- Typecheck (`tsc --noEmit`) and lint clean, consistent with how the 2026-07-22 change was verified (no test framework exists in this repo).

---

## Documentation plan

- Update `TAPIS_AUTH.md`/README as needed only if setup steps change (unlikely — no new env vars or auth surface here).
- No DSO-Architecture docs impact (no new service, port, or auth pattern).

---

## Rollout/rollback plan

1. Ship backend migration + schema/service/route changes first (additive, no frontend dependency yet — old frontend keeps working against the new API unchanged).
2. Ship frontend `GeometryMap` extension + `AddNoteForm`/`MeasurementNoteCallout` changes.
3. Rollback: migration is purely additive (drop column if ever needed); no data loss risk to existing notes since `location` is nullable and unused by other scopes.

---

## Open questions

1. **Marker visual design:** exact color/icon choice for "measurement pin" vs. "note pin" in the callout — a UI/UX call, not architectural, but needs an answer before frontend implementation.
2. **What happens to a note's location if the note is edited by someone other than the picker** — not applicable yet since only the author can edit (existing rule holds), just confirming no new access-control question is introduced.

---

## Decisions

- **2026-07-23:** Point-only geometry (no lines/polygons) for this iteration — user decision.
- **2026-07-23:** Measurement notes only get an independent location; other scopes never expose the field — user decision.
- **2026-07-23:** Both the measurement's location and the note's own location are shown together, not one replacing the other — user decision.
- **2026-07-23:** Reuse the existing WKT-in/GeoJSON-out geometry pattern from `Measurement` rather than inventing a new representation.
- **2026-07-23 (post-architect-review):** Enforce the measurement-only restriction via a schema split (`MeasurementNoteCreate`/`MeasurementNoteUpdate` subclassing the base schemas) rather than a shared schema plus a runtime 400 — makes the restriction visible in the OpenAPI spec/generated SDK and structurally unreachable from the other three routes, not just checked at runtime.
- **2026-07-23 (post-skeptic-review):** `MeasurementNoteUpdate.location` follows this API's existing "PATCH is a full replacement" convention (matching `content`, which is already required on every update) — always send the desired value, `null`/omitted clears it. No new partial-update semantics introduced.
- **2026-07-23 (post-skeptic-review):** `GeometryMap.calculateBounds` will be extended to include marker positions, not just the base geometry, so an intentionally-offset note location can't render off-viewport.
- **2026-07-23 (post-architect-review):** Note-location read-back uses `to_shape`/`shapely.mapping()` (Python-level), a deliberate, documented departure from the SQL-level `ST_AsGeoJSON` idiom used elsewhere, accepted given small note-list sizes.
- **2026-07-23 (post-skeptic-review):** No DB-level `CHECK` constraint or spatial index added in this iteration — both are documented as accepted, low-likelihood residual gaps rather than solved preemptively (see Risks and API schema changes).

---

## User feedback / decisions

- **2026-07-23:** Confirmed scope via clarifying questions: point-only, measurement-scope-only, dual display of measurement + note location.
- **2026-07-23:** Architect and skeptic review completed in parallel. Architect: sound with changes — recommended the schema split (adopted). Skeptic: revise, not reject — flagged the `calculateBounds` viewport bug (fixed in design) and the unenforced scope restriction (fixed via schema split, residual gap on non-API write paths documented rather than solved).
- **2026-07-23:** Implemented as designed, with deviations discovered during implementation:
  - No `packages/upstream-api` SDK regeneration was needed — the notes hooks (`useNotes.ts`) use hand-written `fetch` calls and a local `Note` TypeScript type, not the generated SDK. Added `location` directly to that local type instead.
  - A second, previously-undiscovered frontend consumer of `useCreateMeasurementNote` exists — `src/app/Sensor/viz/HeatMapViz.tsx` (a heatmap view with its own measurement-note panel, separate from the chart callout). Updated its call site for the new `{content, location}` mutate signature; left `enableLocationPicker` off there since it has no measurement geometry readily available to center a picker on — a follow-up if that view should get the picker too.
  - `shapely` was not actually installed (`geoalchemy2` only requires it optionally, for `to_shape`/`from_shape`). Added `shapely` and `types-shapely` to `requirements.txt`.
  - Added `src/app/common/Notes/LocationPickerField.tsx`, a small shared component (toggle + interactive map + clear button) reused by both `AddNoteForm` (new notes) and `NotesList`'s inline edit mode (editing an existing note's location) — not called out explicitly in the original file list but implied by "reuses the same interactive picker" in the Frontend section.
  - Added `tests/test_note_location.py` (9 tests) covering the repository/service round-trip and the schema-layer scope restriction — full suite now 161 passing (152 pre-existing + 9 new), mypy clean across `app/`.
