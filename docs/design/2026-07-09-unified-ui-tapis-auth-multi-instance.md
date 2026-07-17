# Unified UI with Tapis Auth, OAuth, and Stack-Based Multi-Instance Discovery

**Status:** Partially Implemented (2026-07-17: the `/user-roles/me` permission-label fix described in the 2026-07-17 Decisions is implemented and tested — see summary at the end of this doc. Other phases of this spec — OAuth redirect, Stacks-based bundle creation — remain as originally scoped/unimplemented)

---

## Objective

Replace per-bundle UI pod deployments with a single shared Upstream UI that:
- authenticates via Tapis OAuth (with username/password fallback for SDK/API clients),
- discovers which Tapis **Stacks** the user has access to (each stack = one project),
- shows an always-visible project dropdown grouped by permission tier (Owner / Editor / Viewer),
- routes all API queries to the selected project's API pod using the Tapis JWT directly.

---

## User need

**Primary users:** Researchers and data managers granted access to one or more Upstream project deployments (Tapis stacks).

**Secondary users:** Platform operators who want to reduce pod count, simplify permission management, and stop maintaining a per-project UI pod.

**Job-to-be-done:** Access and explore any of their projects' sensor data from one URL, with one login, without knowing deployment details.

**Current pain:**
- Three projects = three UI pod URLs, three login sessions.
- The UI pod is identical code re-deployed per bundle. UI releases require touching every running pod.
- Per-pod permission management is tedious: granting a user access means hitting multiple pods separately.

**Definition of success:**
- One login (Tapis OAuth or username/password) to a single stable URL.
- A persistent nav-bar dropdown lists all accessible stacks, grouped: **Owner (ADMIN) · Editor (USER) · Viewer (READ)**.
- Single-project users land directly on their project; the dropdown remains available to switch.
- Selecting a project routes all queries to that project's API pod via the Tapis JWT — no second login.

---

## Current system summary

### Pod bundle today

`PodsService.build_bundle()` creates three pods + one volume per project:

| Resource | ID pattern | Purpose |
|----------|-----------|---------|
| Volume | `{base}volume` | Persistent Postgres data |
| Pod | `{base}postgres` | PostGIS 17 database |
| Pod | `{base}api` | Upstream FastAPI + Alembic |
| Pod | `{base}` (UI) | Static Nginx + React, `VITE_UPSTREAM_API_URL` hardcoded |

Permissions are granted individually to each pod and the volume via `set_pod_permission` / `set_volume_permission`.

### DB engine

`app/db/session.py` creates a module-level SQLAlchemy engine from `settings.DATABASE_URL` at import time — one engine per API pod process.

### Auth today

1. Username/password → `POST /api/v1/token` → Upstream HS256 JWT + Tapis tokens.
2. Upstream JWT in `localStorage`; Tapis tokens in `sessionStorage`.
3. Inside a Tapis pod, the proxy also injects `X-Tapis-Username/Tenant/Site` headers (pod auth mode).
4. **Added 2026-07-09:** The API now validates Tapis RS256 JWTs directly (`TapisTokenVerifier`), so the Tapis access token can be used as a `Bearer` token with no Upstream JWT exchange.

### CORS confirmation (2026-07-09)

The browser **can** call the Tapis Pods API directly from `*.pods.portals.tapis.io`. No server-side proxy is required for Tapis API calls.

---

## Proposed design

### Overview

```
Single Upstream UI  (one pod or static host, stable URL)
        │
        │  1. Tapis OAuth redirect  (or username/password → /api/v1/token)
        │     → Tapis JWT stored in sessionStorage
        │
        │  2. Browser calls Tapis Pods API directly (CORS OK on portals)
        │     GET /v3/pods/stacks   →  list of stacks user can access
        │     Each stack = one Upstream project
        │
        │  3. Nav-bar project dropdown (always visible)
        │     grouped: Owner · Editor · Viewer
        │
        ▼
Selected stack's {base}api pod
        Bearer: <tapis_jwt>   ← RS256-validated by TapisTokenVerifier
        Each API pod queries its own Postgres pod
```

---

### Tapis Stacks — the new project primitive

Tapis Stacks group related pods with **shared permissions and combined lifecycle control** (start / stop / restart together, with `depends_on` ordering). Granting access to a stack grants access to every member pod at once.

**Impact on bundle creation:**

`build_bundle` will create a Stack instead of managing pods individually:

| Resource | Change |
|----------|--------|
| Stack `{base}` | **New** — created first; `description` = user-facing project name |
| Volume `{base}volume` | unchanged |
| Pod `{base}postgres` | `stack_id: {base}` added to payload |
| Pod `{base}api` | `stack_id: {base}` added; tag `upstream-api: true` for filtering |
| Pod `{base}` (UI) | **Removed** — no longer created |
| Per-pod permission calls | **Replaced** by a single stack-level permission grant |

The stack `description` field becomes the human-readable display name in the UI dropdown. Operators set it at bundle creation time.

---

### Auth flow

#### Primary: Tapis OAuth redirect

```
User visits unified UI
→ Redirected to https://portals.tapis.io/v3/oauth2/authorize
   ?client_id=upstream-ui
   &redirect_uri=https://upstream.pods.portals.tapis.io/callback
   &response_type=code
→ User authenticates with Tapis
→ Redirected back with auth code
→ UI exchanges code for Tapis JWT (access + refresh)
→ Tapis JWT stored in sessionStorage
```

A Tapis OAuth client (`upstream-ui`) must be registered with portals tenant. The redirect URI is the unified UI's stable URL.

#### Fallback: username/password (SDK and API clients)

`POST /api/v1/token` with username/password continues to work unchanged. It returns both the Upstream HS256 JWT (for backward compat) and the Tapis JWT. SDK and existing API clients are unaffected.

#### Token expiry

Tapis JWTs expire in ~4 hours. On expiry, the UI shows a "Session expired — please log in again" banner and clears the stored token. No silent refresh.

---

### Project discovery and dropdown

After login the browser calls Tapis directly:

```
GET https://portals.tapis.io/v3/pods/stacks
X-Tapis-Token: <user_jwt>
```

Filter to stacks that contain at least one pod tagged `upstream-api: true`. Each matching stack becomes one entry in the dropdown.

**Amended 2026-07-17:** The group a project appears under (Owner / Editor / Viewer) is **not** the Tapis stack/pod permission level. It is the current user's row in that project's own `user_roles` DB table (`NONE`/`READ`/`USER`/`APPROVEDADMIN`/`ADMIN`), fetched via a new `GET /api/v1/user-roles/me` call to each discovered project's API pod (Bearer: Tapis token). Tapis pod/stack permission remains an infra-only concept (who can start/stop/delete the pod) and is no longer read for UI grouping. Projects where the resolved role is `NONE` are excluded from the dropdown entirely — see Decisions.

**Dropdown behavior:**
- Rendered as a persistent nav-bar component — always accessible, not a one-time blocking screen.
- Grouped: **Owner** (ADMIN) → **Editor** (USER) → **Viewer** (READ).
- If the user has exactly one accessible stack, the UI auto-selects it and loads immediately. The dropdown remains visible so they can switch if they gain access to more later.
- Selected stack persisted in `sessionStorage`; restored on page reload.
- Pod URL for the selected stack: derived from the stack's API pod networking URL (`{base}api.pods.portals.tapis.io`), read from the pod's `networking.default.url` field in the Tapis response.

```
┌─ Upstream  [Sniffer 2024 ▾] ──── nav items ──── [Alice ▾] ┐
│                                                              │
│  ┌ Sniffer 2024 dropdown ─────────────────┐                 │
│  │  Owner                                  │                 │
│  │    ● Sniffer Campaign 2024  ✓           │                 │
│  │    ● Hurricane Irma Archive             │                 │
│  │  Editor                                 │                 │
│  │    ● Gulf Coast Monitoring              │                 │
│  │  Viewer                                 │                 │
│  │    ● NOAA Shared Dataset                │                 │
│  └─────────────────────────────────────────┘                 │
└──────────────────────────────────────────────────────────────┘
```

---

### Dynamic API routing

`useConfiguration` becomes instance-aware:

```typescript
// reads from InstanceContext instead of window.__UPSTREAM_CONFIG__
const { selectedInstance } = useInstanceContext();
const basePath = selectedInstance?.apiUrl
  ?? window.__UPSTREAM_CONFIG__?.VITE_UPSTREAM_API_URL   // legacy fallback
  ?? import.meta.env.VITE_UPSTREAM_API_URL;

return new Configuration({
  basePath,
  headers: { Authorization: `Bearer ${tapisToken}` },
});
```

When `VITE_UPSTREAM_API_URL` is set (existing per-project UI pods), it overrides discovery and the selector is hidden. This keeps per-project pods working without code changes.

---

---

## Files likely affected

### Backend (`upstream-docker-pods`)

| File | Change |
|------|--------|
| `app/services/pods_service.py` | Create Stack first; add `stack_id` to each pod payload; add `upstream-api` tag to API pod; single stack permission grant; remove UI pod |
| `app/api/v1/routes/pods.py` | Minor: `POST /pods/bundle` response shape update (no UI pod in result) |
| `app/core/config.py` | Possibly add `TAPIS_OAUTH_CLIENT_ID`, `TAPIS_OAUTH_REDIRECT_URI` settings |
| `app/api/v1/routes/user_roles.py` | **New (2026-07-17):** `GET /user-roles/me`, depends on `get_current_user`, returns `{username, role}` for the caller — no admin gate |

### Frontend (`upstream-ui`)

| File | Change |
|------|--------|
| `src/contexts/AuthContext.tsx` | Add OAuth redirect flow; Tapis JWT as primary credential |
| `src/hooks/api/useConfiguration.ts` | Read base URL from `InstanceContext`; `VITE_UPSTREAM_API_URL` as legacy fallback |
| `src/utils/tapisAuth.ts` | Add `fetchUserStacks()` calling Tapis Pods directly; OAuth code exchange helpers |
| `src/contexts/InstanceContext.tsx` | **New** — stack list, selected stack, `sessionStorage` persistence. **Amended 2026-07-17:** `fetchInstances()` also calls `GET {apiUrl}/api/v1/user-roles/me` per discovered pod (parallel) to resolve real permission; drops instances resolving to `NONE` |
| `src/components/NavBar/ProjectDropdown.tsx` | **New** — grouped stack selector in nav bar |
| `src/App.tsx` | Wrap with `InstanceProvider`; render `ProjectDropdown` in nav |
| `docker-entrypoint.sh` | `VITE_UPSTREAM_API_URL` becomes optional |

---

## API/schema changes

### Backend
No database schema changes. No new backend endpoints required for stack/pod discovery itself (browser calls Tapis directly). The optional `GET /api/v1/pods/instances` proxy endpoint is removed from scope — CORS is not a concern.

`build_bundle` response shape changes: `ui` key removed, `stack` key added.

**Added 2026-07-17:** One new backend endpoint, `GET /api/v1/user-roles/me`, is required after all — not for pod/stack discovery, but for resolving the caller's real per-project DB role once a project's API pod is known. It reuses the existing `get_current_user` dependency (already accepts a raw Tapis RS256 bearer token, no new auth mechanism) and returns `{username, role}`. No new DB tables or migrations — reads the existing `user_roles` table.

### Tapis (operator action)
Register an OAuth2 client `upstream-ui` with the portals tenant, redirect URI `https://upstream.pods.portals.tapis.io/callback`. This is a one-time Tapis admin action, not a code change.

---

## Data flow

### OAuth login

```
Browser → portals.tapis.io/v3/oauth2/authorize
        ← redirect with ?code=...
Browser → portals.tapis.io/v3/oauth2/tokens  {code, redirect_uri, client_id}
        ← { access_token, refresh_token, expires_in }
sessionStorage["Tapis-Access-Token"] = access_token
sessionStorage["Tapis-Expires-At"]   = now + expires_in
```

### Stack discovery

```
Browser → portals.tapis.io/v3/pods/stacks
            X-Tapis-Token: <access_token>
        ← [{ stack_id, description, pods: [...], permission }]
filter  → stacks with any pod tagged upstream-api: true
InstanceContext.instances = filtered stacks
```

### Project data request

```
Browser → {selected}api.pods.portals.tapis.io/api/v1/campaigns
            Authorization: Bearer <tapis_jwt>

API pod:
  TapisTokenVerifier.verify(jwt)  →  { tapis/username: "alice" }
  resolve_user_role("alice", jwt)  →  "USER"
  query project DB  →  campaigns list
```

---

## Risks and tradeoffs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Tapis OAuth client registration is a blocker | Medium | Register early; username/password path remains for SDK unblocking |
| Stacks API shape is new/undocumented | Medium | Prototype discovery call early; fall back to `GET /v3/pods` with tag filter if stacks endpoint differs |
| Tapis JWT expiry mid-session | Medium | `sessionStorage["Tapis-Expires-At"]` checked on each API call; prompt re-login |
| Per-project UI pods at existing URLs stop being maintained | Low | They continue working via Upstream JWT path; no forced migration |
| Single-project users confused by always-visible dropdown | Low | Show dropdown greyed/disabled (with tooltip) if only one stack exists |
| **(2026-07-17)** Same Tapis token sent to N independently-operated project pods (all cross-origin, CORS is wildcard `allow_origins=["*"]` app-wide) — widens the token's trust boundary; a compromised/malicious project pod could capture and replay it | Medium | **Accepted for now** (user decision 2026-07-17) — documented, not mitigated in this change. Tightening CORS is a separate, larger change affecting every route/client in this API and needs its own scoped review. |
| **(2026-07-17)** A project's resolved role can go stale: if access is revoked mid-session, an already-selected instance keeps being queried until the next dropdown reload (`fetchedRef`/manual `reload()` only) | Low-Medium | **Accepted** — the dropdown is advisory; real enforcement is the per-request `get_viewer_user`/`get_edit_user`/`get_admin_user` gate inside each project, which still applies regardless of dropdown staleness. |
| **(2026-07-17)** Per-instance role lookup can fail for reasons unrelated to access (pod down/restarting — sample data shows `status: "ERROR"` pods, timeout, 5xx) | Medium | Distinguish "no access" (role `NONE` or 401/403 → drop) from "unknown" (network/5xx/timeout → keep instance, mark `permission: 'UNKNOWN'`, rendered as an "Unverified" group rather than silently disappearing) |

---

## Alternatives considered

**A. Server-side proxy for Tapis Pods discovery**
Originally planned to avoid CORS. Confirmed unnecessary — the portals domain allows direct browser calls. Removed from scope.

**B. Single multi-tenant API (one API pod, multiple databases)**
One API pod with a central project registry managing connections to all project databases, with per-request Tapis permission gates. Evaluated and rejected: all project DB credentials aggregate in one pod (wider blast radius on compromise), and the engineering cost — per-project engine registry, per-request Tapis permission checks, Alembic migration strategy across N databases, URL restructuring — isn't justified. Per-project API + DB pods are kept.

**C. Static instance list in `window.__UPSTREAM_CONFIG__`**
Simple, no Tapis integration. Ignores RBAC; requires redeployment to add/remove projects. Rejected.

**D. Per-project UI pods (status quo)**
Identical code N times. N logins. Rejected as the driver for this spec.

---

## Test plan

### Backend
- Unit: `build_bundle` creates Stack, both pods with `stack_id`, no UI pod — verify payload shapes.
- Unit: stack permission grant replaces per-pod grants — verify single call with correct level.
- Integration: `POST /api/v1/token` still works; Tapis JWT accepted as `Bearer` by project API pod.

### Frontend
- Unit: `InstanceContext` — stacks load on mount, filtering correct, selection persisted/restored, cleared on logout.
- Unit: `ProjectDropdown` — groups render in correct order (Owner → Editor → Viewer), auto-selects when one stack, stays visible after selection.
- Unit: `useConfiguration` — uses selected instance URL; falls back to `VITE_UPSTREAM_API_URL` when set.
- Unit: OAuth callback — code exchange stores token correctly; error states handled.
- Manual E2E: OAuth login → stack list → select project → campaigns load from correct API URL.
- Manual E2E: username/password login via `/api/v1/token` still works (SDK compat).

**Added 2026-07-17:**
- Unit (backend): `GET /user-roles/me` returns the caller's own `{username, role}` for a valid Tapis bearer token; 401 for no/invalid token.
- Unit (backend): `get_current_user`'s dev-mode bypass no longer applies when `TAPIS_ENFORCE_AUTH_IN_DEV=true`, even with `ENV=dev` — must return 401 for a missing/invalid token in that config, not the fake `test` user.
- **Non-dev integration test required:** the dev-mode bypass (`ENV=dev`) makes every `/user-roles/me` call return the same fixed role regardless of the real per-project DB row, masking the multi-role scenario this feature exists to render correctly. Verification must run against a non-dev config (or `TAPIS_ENFORCE_AUTH_IN_DEV=true`) with at least two projects where the same user has different DB roles (e.g. `ADMIN` on one, `READ` on another) and confirm the dropdown groups them correctly — a dev-mode-only pass is not sufficient signoff.
- Unit (frontend): `InstanceContext.fetchInstances()` — per-instance role resolution uses `Promise.allSettled`; a `NONE`/401/403 result drops the instance, a network/5xx/timeout result keeps it with `permission: 'UNKNOWN'`; verify a single failing pod doesn't affect other pods' results (no `Promise.all` fail-all behavior).
- Manual: confirm an "Unverified" group renders in `ProjectDropdown` for a pod that's unreachable/erroring, distinct from a pod correctly resolving to `READ`.

---

## Documentation plan

- Update `TAPIS_AUTH.md`: OAuth flow, stack-based discovery, token expiry behavior.
- Update `upstream-ui/README.md`: `VITE_UPSTREAM_API_URL` is optional; OAuth client setup.
- Add operator runbook: register OAuth client; how `build_bundle` now works (stacks); granting user access via stack permissions.

---

## Rollout/rollback plan

1. **Phase 1 — Tapis JWT as primary auth** (backend already done): Backward-compatible. Ships now.
2. **Phase 2 — Stack-based bundle creation** (backend): New bundles use stacks. Existing bundles are unaffected.
3. **Phase 3 — Stack discovery + nav dropdown** (frontend): Gated by `VITE_ENABLE_INSTANCE_DISCOVERY=true`. Per-project UIs continue working via `VITE_UPSTREAM_API_URL` override.
4. **Phase 4 — OAuth redirect**: Requires Tapis OAuth client registration. Can ship independently of other phases.
5. **Rollback**: Disable feature flag; restore `VITE_UPSTREAM_API_URL`. No DB migrations at any phase.

---

## Open questions

1. ~~**Stacks API shape (needs testing):** Exact shape of `GET /v3/pods/stacks` response is unknown — specifically whether the caller's permission level is included per stack, or whether a separate call is needed. Must be verified before implementing the discovery step.~~ **Resolved 2026-07-17 (moot):** discovery uses `GET /v3/pods`, not `/v3/pods/stacks`, and the dropdown no longer reads permission from Tapis at all (see Decisions). Whether Tapis's stacks endpoint includes a permission field is no longer relevant to this design.
2. **Upstream-api tag field (needs testing):** Which Tapis Pods field holds custom tags — `environment_variables`? A dedicated `tags` field? Needs verification against the Tapis Pods API schema before `build_bundle` can tag the API pod reliably.
3. **Per-project UI pod deprecation:** No timeline set yet. To be decided once the unified UI is stable.
4. **Stack permissions granularity:** When a user is granted ADMIN on a stack, do they automatically get ADMIN on all member pods and the volume? Needs confirmation — the design assumes yes, but behavior should be verified during the Phase 2 prototype.

---

## Decisions

*(Record decisions here as they are made using the decision-log skill.)*

### 2026-07-17 — Dropdown permission label switches from Tapis pod permission to per-project DB role

- **Decision:** The ProjectDropdown's Owner/Editor/Viewer grouping is driven by each project's own `user_roles` DB table for the current user (`NONE`/`READ`/`USER`/`APPROVEDADMIN`/`ADMIN`, resolved server-side via `resolve_user_role()`), not by Tapis stack/pod-level permission (`ADMIN`/`USER`/`READ`, an infra/ops-control concept — who can start/stop/delete the pod).
- **Reason:** As implemented, `InstanceContext.tsx` discovers pods via `GET /v3/pods` (the Stacks-based approach from this spec's original design was never completed) and hardcodes `permission: 'ADMIN'` for every discovered instance, so every project showed as "Owner" regardless of real access — reported as a bug 2026-07-17. Investigating the fix surfaced that Tapis pod permission and the app's DB `user_roles` are two distinct systems that happen to share similar level names; conflating them was the root confusion. The DB role is the one that already gates real data access (`get_viewer_user`/`get_edit_user`/`get_admin_user`), so it's the correct source for a user-facing access label.
- **Alternatives rejected:** (1) Fetch the real Tapis pod/stack permission via `GET /v3/pods/{pod_id}/permissions` and use that instead — rejected because that endpoint requires USER-level Tapis pod access, so it would 403 for exactly the READ-level users the fix targets, and because it answers "can this user manage the pod's infrastructure," not "can this user see this project's data," which is what the dropdown is actually communicating. (2) Unify Tapis pod permission and the DB `user_roles` into one model — rejected as larger, riskier surgery (rewriting pod-creation grants and/or the `get_viewer_user`/`get_edit_user`/`get_admin_user` checks, reconciling differing level sets since Tapis has no `NONE`/`APPROVEDADMIN`) with no clear benefit over keeping the two concerns separate.
- **User feedback:** User confirmed via direct question: "Keep them separate, fix the label" (2026-07-17).
- **Impact on implementation:** Adds a new `GET /api/v1/user-roles/me` backend endpoint (see Files likely affected / API changes above) and a per-instance role-resolution step in `InstanceContext.tsx`'s `fetchInstances()`. Resolves Open Question #1 as moot.

### 2026-07-17 — Hide NONE-role projects from the dropdown

- **Decision:** If a discovered project resolves to DB role `NONE` for the current user, it is excluded from the Project dropdown entirely — not shown greyed-out, not left to backend gating alone.
- **Reason:** Avoids a user selecting a project they have zero data access to and immediately hitting 403s inside it once selected.
- **Alternatives rejected:** Show it greyed out/unselectable (adds UI complexity for a state that isn't actionable by the end user); show it normally and rely on existing `get_viewer_user`/`get_edit_user`/`get_admin_user` gates inside the project (selectable-but-broken UX).
- **User feedback:** User selected this option directly when asked (2026-07-17).
- **Impact on implementation:** `InstanceContext.tsx`'s `fetchInstances()` filters out any instance whose resolved role is `NONE` (or unresolvable) after the `GET /api/v1/user-roles/me` calls, before setting `instances` state.

### 2026-07-17 — Team discourse (architect / security-reviewer / skeptic) and final implementation adjustments

- **Decision:** Proceed with the plan from the two decisions above, with these required corrections surfaced by review:
  1. Use `Promise.allSettled` (not `Promise.all`) for the per-instance `/user-roles/me` calls, with a concurrency cap (~6 in flight), so one slow/failing pod can't block or fail the whole dropdown (architect + skeptic).
  2. Distinguish real "no access" (role `NONE`, or 401/403) — drop the instance — from "unknown" (network error, 5xx, timeout) — keep the instance with a new `permission: 'UNKNOWN'` state, rendered as an "Unverified" group in `ProjectDropdown` rather than silently vanishing (skeptic, highest-ranked concern; sample pod data in this repo already shows real `status: "ERROR"` pods, so this isn't hypothetical).
  3. Fix `get_current_user`'s dev-mode bypass (`app/api/dependencies/auth.py`) to also respect the existing `TAPIS_ENFORCE_AUTH_IN_DEV` setting, matching `authenticate_user()`'s existing `skip_enforcement` logic — i.e. `if settings.ENV == "dev" and not settings.TAPIS_ENFORCE_AUTH_IN_DEV`. Currently the bypass is unconditional on `ENV == "dev"` alone, returning a fake ADMIN user with zero token verification; this feature increases exposure by having the UI auto-call `/user-roles/me` against every discovered pod at login (security-reviewer).
  4. Token fan-out to N project pods under wildcard CORS, and role staleness after a mid-session access revoke, are both **accepted as documented risks** rather than fixed in this change (see Risks and tradeoffs table) — both are broader than this feature's scope (CORS policy affects every route/client; staleness is inherent to any client-side cache without a push-invalidation mechanism, and the real gate is still the per-request backend role check).
- **Reason:** Independent architect, security, and skeptic review before implementation, per this project's Major-tier workflow.
- **Alternatives rejected:** Blocking implementation entirely on a CORS rewrite or a general auth-bypass hardening pass — rejected as disproportionate scope expansion for a permission-label bug fix; the two items are tracked as accepted risks / a narrowly-scoped follow-on fix instead.
- **User feedback:** User chose "Accept for now, document it" for the CORS/token-sharing risk, and "Fix it now as part of this work" for the dev-mode bypass (2026-07-17).
- **Impact on implementation:** Adds a `TAPIS_ENFORCE_AUTH_IN_DEV` check to `get_current_user`; adds an `UNKNOWN` permission state to the frontend `Permission` type and `ProjectDropdown`'s grouping; changes `fetchInstances()` to use `Promise.allSettled` with a concurrency cap instead of `Promise.all`.

### 2026-07-17 — Superseded a prior, non-functional fix attempt on `main` (commit `30caefb`)

- **Decision:** While preparing the PR, discovered that `upstream-ui`'s `main` branch already had a prior fix attempt (commit `30caefb`, "fix: show projects for read-only pod users in discovery mode") that this change supersedes and removes: it added a `?list_type=ALL` query param to `GET /pods` and read `p.owner`/`p.permissions[username]` fields directly off each Tapis pod object, assuming Tapis exposes per-user access level inline in the pod list response.
- **Reason:** Verified against the actual Tapis Pods service source (`tapis-project/pods_service`, `service/api_pods.py` and `service/models_pods.py`) that neither assumption holds: `GET /pods` accepts no `list_type` parameter at all (FastAPI silently ignores the unknown query string), and the endpoint's `pod.display()` serializer explicitly does `display.pop('permissions')` before returning pod data to the client — there is no `owner` field on the pod model in the first place. Also confirmed `GET /pods` already returns every pod the caller has READ-or-higher access to by default (`Pod.db_get_all_with_permission(..., level='READ', ...)`), so `list_type=ALL` was solving a problem that didn't exist. Net effect on `main` today: `p.permissions?.[username]` and `p.owner` are always `undefined`, so every instance's permission was silently stuck at the code's `'READ'` default (or `'ADMIN'` only when a username couldn't be decoded from the token at all) — never the user's real access level. This was very likely written and merged without validation against a live Tapis response (co-authored by a prior AI session).
- **Alternatives rejected:** Leaving `30caefb`'s logic in place alongside the new `/user-roles/me` call (defense in depth) — rejected as needless complexity; the old fields will never populate, so keeping the dead code only invites a future reader to trust it.
- **User feedback:** Surfaced to the user during PR preparation as a "let's go ahead" continuation of already-approved work, not a new open decision — noted here for the record since it changes what the PR actually removes/supersedes on `main`.
- **Impact on implementation:** `InstanceContext.tsx`'s `TapisPod` interface drops `owner`/`permissions`; `getUsernameFromTapisToken()` (unused once the backend resolves username from the token itself) is removed; the `?list_type=ALL` query param is dropped from both the direct and `/tapis-proxy/` pod-list URLs. `main`'s other, unrelated improvements to this file (the `[upstream]`-marker-only filter from `ce0b06e`, the `'upstream'`-stackId auto-select preference, debug logging) are preserved as-is.

---

## User feedback / decisions

- **2026-07-09:** Project selector should be a persistent nav-bar dropdown, not a blocking one-time screen. Single-project users auto-land on their project but the dropdown remains available.
- **2026-07-09:** Dropdown groups instances by Tapis permission tier: Owner (ADMIN) · Editor (USER) · Viewer (READ).
- **2026-07-09:** CORS confirmed — browser can call Tapis Pods API directly from `*.pods.portals.tapis.io`. Server-side proxy removed from scope.
- **2026-07-09:** Move to Tapis OAuth redirect as primary auth. Username/password (`/api/v1/token`) stays for SDK and API client backward compatibility.
- **2026-07-09:** Token expiry → prompt re-login (no silent refresh).
- **2026-07-09:** Portals tenant only (no multi-tenant support needed).
- **2026-07-09:** Per-project UI pod deprecation timeline TBD.
- **2026-07-09:** Tapis Stacks adopted as the project primitive — each bundle becomes a stack; stack permissions replace per-pod permission management.
- **2026-07-09:** Stacks API shape and tag field are unknown — must be prototyped/tested before implementation begins. Design assumes stacks expose a permission level and a filterable tag field; actual behavior will drive implementation details.
- **2026-07-09:** A new Tapis OAuth2 client must be registered on the portals tenant. No existing client to reuse. Registering the client is a prerequisite for Phase 4 (OAuth redirect) but does not block Phases 1–3.
- **2026-07-09:** Per-project UI pod deprecation timeline TBD — to be revisited once unified UI is in production.
- **2026-07-09:** Single multi-tenant API (Option B) evaluated and rejected. Each project keeps its own isolated API pod and Postgres pod. Credential aggregation risk and engineering complexity outweigh the benefit of fewer running pods.

---

## Implementation summary (2026-07-17)

Scope actually implemented: the permission-label fix only (Decisions dated 2026-07-17). OAuth redirect and Stacks-based bundle creation from the original spec remain unimplemented.

**Backend (`upstream-docker-pods`):**
- `app/api/dependencies/auth.py` — `get_current_user`'s dev-mode bypass now also requires `not settings.TAPIS_ENFORCE_AUTH_IN_DEV`, matching `authenticate_user`'s existing enforcement flag.
- `app/api/v1/routes/user_roles.py` — added `GET /user-roles/me`, depends on `get_current_user`, no admin gate, returns `{username, role}`.
- Tests added: `tests/api/dependencies/test_auth.py` (dev bypass on/off), `tests/api/v1/routes/test_user_roles.py` (self-lookup with a role, with `NONE` role, and unauthenticated 401). Full backend suite: 141 passed.

**Frontend (`upstream-ui`):**
- `src/contexts/InstanceContext.tsx` — `Permission` type gained `'UNKNOWN'`; `fetchInstances()` now resolves each discovered project's real DB role via `GET {apiUrl}/api/v1/user-roles/me` using `Promise.allSettled` with a concurrency cap of 6 (not `Promise.all`, per architect/skeptic review). `NONE`/401/403 drops the instance; any other failure (network, 5xx, timeout) keeps it tagged `'UNKNOWN'` instead of silently hiding it. This branch also removes `main` commit `30caefb`'s non-functional `owner`/`permissions`/`list_type=ALL` approach — see the 2026-07-17 "Superseded a prior, non-functional fix attempt" decision above — while keeping `main`'s unrelated improvements to this file (the `[upstream]`-marker-only filter, `'upstream'`-stackId auto-select preference, debug logging).
- `src/app/_Layout/_components/Header/_components/ProjectDropdown.tsx` — added an "Unverified" group for `UNKNOWN` permission.
- Verified: `tsc -b --noEmit` clean, `eslint` clean (one pre-existing, unrelated warning).

**Deviations from the pre-2026-07-17 design:** dropdown grouping source switched from Tapis pod permission to DB `user_roles`; NONE-role projects hidden; dev-bypass hardening added; CORS/token-fan-out and role-staleness accepted as documented risks rather than fixed; `main`'s prior (non-functional) permission-resolution attempt removed and replaced.

**Not done / follow-ups:** CORS tightening (accepted risk, tracked separately); dropdown does not re-check role mid-session on revoke (accepted, backend per-request role gates remain the real enforcement); Tapis OAuth redirect and Stacks-based bundle creation (out of scope for this change, unimplemented since original spec).
