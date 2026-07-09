# Unified UI with Tapis Auth, OAuth, and Stack-Based Multi-Instance Discovery

**Status:** In Review

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

Filter to stacks that contain at least one pod tagged `upstream-api: true`. Each matching stack becomes one entry in the dropdown. The user's permission level on the stack (`ADMIN` / `USER` / `READ`) determines the group it appears under.

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

### Frontend (`upstream-ui`)

| File | Change |
|------|--------|
| `src/contexts/AuthContext.tsx` | Add OAuth redirect flow; Tapis JWT as primary credential |
| `src/hooks/api/useConfiguration.ts` | Read base URL from `InstanceContext`; `VITE_UPSTREAM_API_URL` as legacy fallback |
| `src/utils/tapisAuth.ts` | Add `fetchUserStacks()` calling Tapis Pods directly; OAuth code exchange helpers |
| `src/contexts/InstanceContext.tsx` | **New** — stack list, selected stack, `sessionStorage` persistence |
| `src/components/NavBar/ProjectDropdown.tsx` | **New** — grouped stack selector in nav bar |
| `src/App.tsx` | Wrap with `InstanceProvider`; render `ProjectDropdown` in nav |
| `docker-entrypoint.sh` | `VITE_UPSTREAM_API_URL` becomes optional |

---

## API/schema changes

### Backend
No database schema changes. No new backend endpoints required for discovery (browser calls Tapis directly). The optional `GET /api/v1/pods/instances` proxy endpoint is removed from scope — CORS is not a concern.

`build_bundle` response shape changes: `ui` key removed, `stack` key added.

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

1. **Stacks API shape (needs testing):** Exact shape of `GET /v3/pods/stacks` response is unknown — specifically whether the caller's permission level is included per stack, or whether a separate call is needed. Must be verified before implementing the discovery step.
2. **Upstream-api tag field (needs testing):** Which Tapis Pods field holds custom tags — `environment_variables`? A dedicated `tags` field? Needs verification against the Tapis Pods API schema before `build_bundle` can tag the API pod reliably.
3. **Per-project UI pod deprecation:** No timeline set yet. To be decided once the unified UI is stable.
4. **Stack permissions granularity:** When a user is granted ADMIN on a stack, do they automatically get ADMIN on all member pods and the volume? Needs confirmation — the design assumes yes, but behavior should be verified during the Phase 2 prototype.

---

## Decisions

*(Record decisions here as they are made using the decision-log skill.)*

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
