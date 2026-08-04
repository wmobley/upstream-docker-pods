# Tapis Silent Token Refresh

**Status:** Draft

---

## Objective

Enable Tapis access tokens to be silently refreshed before expiry instead of forcing a hard logout. This allows users to continue long-running workflows (e.g., bulk sensor data uploads) without interruption when their ~4-hour Tapis token expires mid-session.

---

## User need

**Primary user:** Researchers and data managers uploading large amounts of sensor data through the Upstream UI in sessions that may exceed the Tapis token's ~4-hour TTL.

**Secondary users:** Platform operators who want to reduce friction in data entry workflows and minimize support requests about unexpected session timeouts.

**Job-to-be-done:** Complete multi-file, multi-step data upload workflows without being forcibly logged out mid-workflow due to token expiry.

**Current pain:**
- Token expiry (@~4 hours) is hard-coded by Tapis and not configurable via OAuth2 client registration.
- The current implementation (decision logged in 2026-07-09 spec, section ~line 140) deliberately avoids silent refresh: it fires a `setTimeout` at the expiry timestamp, then clears all tokens and forces a re-login.
- This is a blocker for users with long-running uploads or extended analysis sessions.
- Production logs (reviewed by user) confirm the failure mode: many separate, sequential `POST /uploadfile_csv/campaign/1/station/1/sensor` calls succeed in a single user session, each one bounded to a single HTTP request. Token expiry partway through the session kills subsequent requests. This is exactly the scenario silent refresh fixes (session with many sequential short requests, not one request with long processing time).

**Definition of success:**
- A user uploading sensor data continuously across a 4-hour period is NOT logged out automatically.
- The token is transparently refreshed before expiry using the stored refresh token.
- If a refresh fails (e.g., refresh token is revoked or expired), the system gracefully degrades to the existing hard-logout behavior, asking the user to log in again.
- The user does not see "Session expired" errors mid-workflow unless the refresh token itself is invalid.

**Assumptions:**
- Tapis `refresh_token` is longer-lived than `access_token` and remains valid for the duration of a typical session. (Open Question #2 blocks confirmation.)
- The backend Tapis token endpoint (`POST /v3/oauth2/tokens` with `grant_type=refresh_token`) behaves like standard OAuth2 refresh (verify shape against Tapis docs/tapipy before implementing).
- "Long upload times" means (b) multi-step/multi-file upload workflows made of many sequential requests (CONFIRMED by production logs), not (a) a single HTTP request with processing time exceeding 4 hours (the latter cannot be fixed by client-side refresh alone).

---

## Current code/system summary

### Token storage and expiry (today)

- **AuthContext.tsx** (lines 56–82): Stores `Tapis-Expires-At` timestamp in `sessionStorage` and sets a client-side `setTimeout` that fires exactly at expiry. When it fires, the timer calls `expire()`, which clears all tokens and logs the user out.
- **tapisAuth.ts**: Stores access, refresh, and expiry in `sessionStorage` under keys `Tapis-Access-Token`, `Tapis-Refresh-Token`, and `Tapis-Expires-At`.
- **root.py** (login endpoint): Backend already returns all three: `tapis_access_token`, `tapis_refresh_token`, `tapis_expires_at` (~4 hours from now as Unix timestamp).

### Token usage in API calls

- **useConfiguration.ts** (lines 18, 59): On every API request, reads the current token fresh from `sessionStorage('Tapis-Access-Token')` and includes it as `Authorization: Bearer <token>`. This means any refreshed token written to sessionStorage is automatically used by subsequent requests without additional code changes.

### OAuth2 refresh precedent

- **tapisAuth.ts** (lines 260–292): Already implements `exchangeOAuthCode()` which POSTs to `{TAPIS_BASE_URL}/v3/oauth2/tokens` with `grant_type=authorization_code`. A refresh call would POST the same endpoint with `grant_type=refresh_token` and the stored refresh token instead of a code.

### Deliberate design decision to supersede

- **2026-07-09 spec** (line 138–140): Explicitly documented: "Tapis JWTs expire in ~4 hours. On expiry, the UI shows a "Session expired — please log in again" banner and clears the stored token. **No silent refresh.**" This was a simplification trade-off at that time. We now supersede this decision because the pain of long upload sessions warrants the added complexity.

### Test environment

- **upstream-ui** has no test framework currently configured (CLAUDE.md notes this).
- Manual verification will be the primary test strategy; optional: recommend introducing a minimal setup (e.g., Vitest + React Testing Library) if future test coverage is desired.

---

## Proposed design

### High-level flow

```
User logs in
  ↓
Tapis tokens stored: access, refresh, expires_at
  ↓
Schedule early refresh: 80% of TTL elapsed
  ↓
[refresh trigger fires]
  ↓
POST /v3/oauth2/tokens with refresh_token
  ↓
On success: update sessionStorage, reschedule next refresh
On failure: fall back to hard logout (existing behavior)
  ↓
[API requests use fresh token from sessionStorage]
```

### Primary mechanism: Scheduled refresh

**When to refresh:** When the current time reaches `expiresAt * 0.8` (i.e., 80% of the token's original TTL has elapsed). This provides a 20% buffer (~48 minutes for a 4-hour token) to catch any clock skew or small processing delays before actual expiry.

**How to schedule (effect-driven, for all session entry paths):**

The refresh schedule must be wired as an effect keyed off `isAuthenticated` state (or equivalent) plus the stored `Tapis-Expires-At`, so it runs uniformly for all three ways a session gets established:
- Fresh login (POST to `/login` endpoint)
- Page reload with existing tokens (bootstrap `checkAuth()` effect, lines ~84-123)
- OAuth callback completion

This mirrors the current hard-logout timer design (AuthContext lines 56–82), which is effect-driven and works across all three entry paths.

**Implementation steps:**

1. In `AuthContext.tsx`, add an effect keyed on `[isAuthenticated]` (or add a separate effect keyed on the stored expiry timestamp read via a getter).
2. On each run of this effect, if `isAuthenticated` is true and tokens exist:
   - Read `Tapis-Expires-At` from sessionStorage.
   - Calculate the refresh time: `refreshAt = expiresAt - (expiresAt - now) * 0.2` (80% threshold).
   - If refreshAt is in the future, schedule a `setTimeout()` to fire at that time.
   - If refreshAt is in the past (token already expired or nearly so), call `expire()` immediately.
3. On timer fire:
   - Attempt to refresh by calling `refreshTapisToken()` (see below).
   - If refresh succeeds: read the new `Tapis-Expires-At` from sessionStorage, reschedule using step 2.
   - If refresh fails with 401 or "invalid_grant": proceed directly to `expire()`.
   - If refresh fails with transient error (network, 5xx): log error, optionally retry with exponential backoff, or proceed to `expire()`.

**State management:** Store `refreshTimerId` to allow cancelling the scheduled timer if the component unmounts or the user logs out.

**Reschedule behavior:** Every successful refresh resets the timeout for the next refresh window, so the schedule is adaptive and doesn't require epoch-level precision.

### Fallback mechanism: On-demand refresh on 401

While the scheduled refresh should cover most cases, also provide a safety net in the API layer:

1. In **useConfiguration.ts** or a new interceptor layer, detect 401 responses.
2. If a 401 occurs and the refresh token is still present, attempt `refreshTapisToken()` once.
3. On success, retry the original request with the new token.
4. On failure, proceed to logout (do not retry the original request; let the error propagate).

**Note:** This is a fallback; the primary mechanism is the scheduled refresh. The on-demand refresh catches edge cases (e.g., token revoked server-side, or a very long single request that outlives the scheduled window).

### New function: `refreshTapisToken()`

Add to **tapisAuth.ts**:

**Key requirement:** Validate the Tapis response shape BEFORE touching storage. If any required field is missing or malformed, throw an error immediately. This prevents a silent wipe of all three tokens (the "fail-silent" scenario where `storeTapisTokens()` clears first, then sets only truthy fields, leaving a zombie session).

```typescript
/**
 * Attempt a silent refresh of the Tapis access token using the stored refresh token.
 * 
 * CRITICAL: Validates the response shape BEFORE updating storage. On any missing or
 * malformed field, throws an error (does NOT partially update storage).
 * 
 * On success, updates sessionStorage with new tokens and returns the new access token.
 * On failure, throws an error (caller decides whether to retry or logout).
 */
export const refreshTapisToken = async (): Promise<string> => {
  const refreshToken = sessionStorage.getItem(TAPIS_REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    throw new Error('No refresh token available');
  }

  const base = getTapisOAuthBaseUrl();
  const clientId = getOAuthClientId();
  const clientKey = getOAuthClientKey();

  // CONFIRMED against tapipy's reference implementation (refresh_user_tokens() in
  // tapipy/tapis.py): the refresh_token grant authenticates the client via HTTP
  // Basic Auth (Authorization: Basic base64(client_id:client_key)), NOT via
  // client_id/client_key in the JSON body like the authorization_code exchange
  // in exchangeOAuthCode() above. Do not copy that pattern here.
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (clientKey) {
    headers['Authorization'] = `Basic ${btoa(`${clientId}:${clientKey}`)}`;
  }

  try {
    const resp = await fetch(`${base}/v3/oauth2/tokens`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
      }),
    });

    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      throw new Error(`Token refresh failed (${resp.status}): ${body}`);
    }

    const data = await resp.json();
    const result = data.result ?? data;
    const accessTokenObj = result.access_token ?? {};
    const refreshTokenObj = result.refresh_token ?? {};

    // VALIDATE response shape BEFORE touching storage.
    // Confirmed shape (Tapis TokenResponse schema, tapipy 25.4.0
    // openapi_v3-authenticator.yml): access_token and refresh_token are each
    // objects with string fields `access_token`/`refresh_token`, plus
    // `expires_at` (a UTC *string*, not a number) and `expires_in` (integer
    // seconds). Compute our own numeric epoch expiry from expires_in — do not
    // try to parse/validate expires_at as a number, it never will be one.
    const newAccessToken = typeof accessTokenObj === 'string'
      ? accessTokenObj
      : accessTokenObj.access_token;
    const newRefreshToken = typeof refreshTokenObj === 'string'
      ? refreshTokenObj
      : refreshTokenObj.refresh_token; // NOT `.access_token` — see prerequisite bug note above
    const expiresIn = accessTokenObj.expires_in;
    const newExpiresAt = typeof expiresIn === 'number'
      ? Math.floor(Date.now() / 1000) + expiresIn
      : undefined;

    // Strict validation: throw if any required field is missing or empty.
    if (!newAccessToken || typeof newAccessToken !== 'string' || newAccessToken.trim() === '') {
      throw new Error('Invalid token refresh response: access_token is missing or empty');
    }
    if (!newRefreshToken || typeof newRefreshToken !== 'string' || newRefreshToken.trim() === '') {
      throw new Error('Invalid token refresh response: refresh_token is missing or empty');
    }
    if (!newExpiresAt || typeof newExpiresAt !== 'number') {
      throw new Error('Invalid token refresh response: expires_in is missing or not a number');
    }

    // All validations passed. Now update storage atomically (do NOT use the destructive 
    // storeTapisTokens() pattern; instead directly set each key to ensure atomic success).
    sessionStorage.setItem(TAPIS_ACCESS_TOKEN_KEY, newAccessToken);
    sessionStorage.setItem(TAPIS_REFRESH_TOKEN_KEY, newRefreshToken);
    sessionStorage.setItem(TAPIS_EXPIRES_AT_KEY, newExpiresAt.toString());

    console.debug('[TapisAuth] Token refreshed successfully; masked new token:', 
      `${newAccessToken.slice(0, 6)}...${newAccessToken.slice(-6)}`);

    return newAccessToken;
  } catch (error) {
    console.warn('[TapisAuth] Token refresh failed:', error);
    throw error;
  }
};
```

### Update AuthContext.tsx

Replace the existing hard-logout timer (lines 56–82) with:

1. **Clear the old `setTimeout` logic** and replace with a scheduled refresh.
2. **Add state** to track the current refresh timer ID so it can be cancelled/rescheduled:
   ```typescript
   const [refreshTimerId, setRefreshTimerId] = useState<ReturnType<typeof setTimeout> | null>(null);
   ```

3. **In the same `useEffect`**, after detecting tokens, schedule the first refresh:
   ```typescript
   const scheduleTokenRefresh = (expiresAt: number, isRetry: boolean = false) => {
     // Clear any existing timer
     if (refreshTimerId) clearTimeout(refreshTimerId);

     const now = Date.now() / 1000;
     const ttl = expiresAt - now;
     if (ttl <= 0) {
       // Token already expired
       expire();
       return;
     }

     // Refresh at 80% of TTL elapsed
     const refreshAt = now + ttl * 0.8;
     const msUntilRefresh = (refreshAt - Date.now() / 1000) * 1000;

     const id = setTimeout(async () => {
       try {
         await refreshTapisToken();
         // On success, getTapisExpiresAt() from sessionStorage and reschedule
         const newExpiresAt = parseInt(sessionStorage.getItem('Tapis-Expires-At') || '0', 10);
         if (newExpiresAt > 0) {
           scheduleTokenRefresh(newExpiresAt);
         }
       } catch (error) {
         console.error('[Auth] Token refresh failed, logging out:', error);
         expire();
       }
     }, msUntilRefresh);

     setRefreshTimerId(id);
   };
   ```

4. **On login success** (after `storeTapisTokens()`), call:
   ```typescript
   if (response.tapisExpiresAt) {
     scheduleTokenRefresh(response.tapisExpiresAt);
   }
   ```

5. **On logout**, clear the timer:
   ```typescript
   const logout = () => {
     if (refreshTimerId) clearTimeout(refreshTimerId);
     // ... rest of logout logic
   };
   ```

6. **Cleanup on unmount:**
   ```typescript
   return () => {
     if (refreshTimerId) clearTimeout(refreshTimerId);
   };
   ```

### Concurrent refresh guard

To prevent a stampede of refresh calls if multiple API requests fail with 401 in quick succession:

- **In tapisAuth.ts**, add module-level state to track the in-flight refresh:
  ```typescript
  let refreshInFlight: Promise<string> | null = null;
  ```

- **In `refreshTapisToken()`, wrap the entire async function logic:**
  ```typescript
  // If a refresh is already in flight, return the same promise so all callers await the same result.
  if (refreshInFlight) {
    console.debug('[TapisAuth] Refresh already in flight; waiting for existing attempt...');
    return refreshInFlight;
  }

  // Start the refresh and store the promise so concurrent calls can await it.
  refreshInFlight = (async () => {
    try {
      // ... perform the actual refresh logic (fetch, validate, store) ...
      const newAccessToken = /* result from validation */;
      return newAccessToken;
    } finally {
      refreshInFlight = null; // Clear the in-flight promise when done (success or failure)
    }
  })();

  return refreshInFlight;
  ```

This ensures all concurrent refresh attempts (e.g., multiple 401s in quick succession) await a single underlying refresh call, then all receive the same new token or the same error.

### Session ceiling / max refresh duration — DECIDED: 7 days

Silent refresh can, in theory, extend a session indefinitely as long as the user keeps making requests and the refresh token remains valid. To prevent unbounded session extension, a **mandatory application-level ceiling is implemented:**

- **Maximum session duration: 7 days**, fixed at the application level, independent of whatever Tapis's own refresh-token TTL turns out to be (Open Question #2). If Tapis's refresh token itself expires sooner than 7 days, that shorter TTL is still the effective limit — the 7-day value is a ceiling, not a guarantee of session length.
- Record the session start time as `Tapis-Session-Started-At` (a Unix timestamp) in `sessionStorage` at login (covering all three session-entry paths: fresh login, page reload, OAuth callback — same effect-driven wiring as the refresh schedule itself).
- On each refresh attempt, check: `now - sessionStartTime > 7 * 24 * 60 * 60` (7 days in seconds). If true, do not refresh; instead call `expire()` and force the user to log in again.
- This ensures silent refresh never creates a session that lives longer than 7 days, regardless of how long the refresh token itself would otherwise remain valid.

See Decisions entry [2026-08-04c].

### Fallback to hard logout

When refresh fails (401, invalid_grant, or transient errors after backoff):
1. Call the existing `expire()` function from AuthContext.
2. Display the existing error message: "Your session has expired. Please log in again."
3. Clear all tokens (already done by `expire()`).

No new UI is needed; the existing error handling in AuthContext is reused.

---

## Files likely affected

### Frontend (upstream-ui)

1. **src/utils/tapisAuth.ts**
   - Add `refreshTapisToken()` function
   - Add concurrent refresh guard (`refreshInFlight` flag or Promise-based coordination)

2. **src/contexts/AuthContext.tsx**
   - Replace hard-logout timer with scheduled refresh
   - Add `refreshTimerId` state
   - Implement `scheduleTokenRefresh()` function
   - Update login path to schedule first refresh
   - Update logout path to cancel timer

3. **src/hooks/api/useConfiguration.ts** (optional fallback)
   - Add 401 interception and on-demand refresh (if decided to implement the fallback mechanism)
   - This may instead be implemented as a fetch interceptor or axios/fetch wrapper if a higher-level HTTP client is adopted later

### Backend (upstream-docker-pods)

**No changes anticipated, pending Open Question #5.** The backend already returns refresh tokens in the login response, and the OAuth2 token endpoint already handles `grant_type=refresh_token` (standard Tapis feature). This assumes every Tapis client/tenant configuration our users authenticate through actually issues a refresh token on login — if some configurations don't, enabling refresh may require a backend or OAuth2-client scope change to request one. Confirm before implementation.

### Tests

- **upstream-ui/tests/** (if created)
  - Tests for `refreshTapisToken()`: mocked fetch, success/failure scenarios
  - Tests for scheduled refresh timing
  - Tests for concurrent refresh guard

---

## API/schema changes

**None to Upstream's own API or schema.** This reuses Tapis's existing `POST /v3/oauth2/tokens` endpoint with `grant_type=refresh_token`, the same endpoint `exchangeOAuthCode()` already calls with `grant_type=authorization_code` — no new Tapis or Upstream endpoint is introduced.

**Resolved** (see Open Question #1 and Decisions [2026-08-04d]): response shape, field names, and auth mechanism for the refresh grant are confirmed against tapipy's bundled OpenAPI spec and reference implementation. The `refreshTapisToken()` sketch above reflects the confirmed shape. Still open: whether Tapis rotates in a new refresh token on every use (the schema allows it — `refresh_token` is present in the response — but doesn't state whether the old one is invalidated); treat the returned `refresh_token` as authoritative and always overwrite the stored one, which the sketch already does.

---

## Data flow

```
1. User logs in (username/password or OAuth2 code)
   ├─ AuthContext calls login()
   ├─ Response includes tapis_access_token, tapis_refresh_token, tapis_expires_at
   └─ tapisAuth.storeTapisTokens() stores all three in sessionStorage

2. AuthContext.scheduleTokenRefresh(expiresAt)
   ├─ Calculates refreshAt = expiresAt * 0.8
   ├─ setTimeout(() => refreshTapisToken(), msUntilRefresh)
   └─ Timer scheduled

3. [80% of TTL elapsed]
   ├─ Timer fires → refreshTapisToken() called
   ├─ POST /v3/oauth2/tokens?grant_type=refresh_token
   ├─ Tapis returns new access_token, refresh_token, expires_at
   ├─ tapisAuth.storeTapisTokens() updates sessionStorage with new values
   ├─ AuthContext reschedules next refresh at 80% of new TTL
   └─ No user interruption

4. [API requests continue normally]
   ├─ useConfiguration.ts reads fresh Tapis-Access-Token from sessionStorage
   ├─ Each request includes Authorization: Bearer <fresh_token>
   └─ Requests succeed (token is valid for another ~4 hours from refresh)

5a. [Refresh succeeds repeatedly until user logs out or session timeout]
   └─ Workflow completes without interruption

5b. [Refresh fails (refresh token revoked, etc.)]
   ├─ refreshTapisToken() throws error
   ├─ AuthContext.expire() called
   ├─ All tokens cleared, user logged out
   └─ User sees "Session expired" and must log in again
```

---

## Risks and tradeoffs

### Risks

1. **Clock skew:** If the client's system clock is significantly ahead of Tapis's, the refresh attempt might occur before Tapis considers the original token expired. Mitigated by calculating refresh time locally and checking the actual response; if "token not yet expired" is returned, we can delay and retry.

2. **Refresh token expiry:** If the refresh token itself expires before the access token, refresh will fail. Mitigation: Tapis typically issues longer-lived refresh tokens, but we should test this assumption. If refresh token TTL is too short, the hard-logout fallback still works.

3. **Network intermittency during refresh:** A transient network error might be mistaken for token revocation. Mitigation: Implement optional exponential backoff retry before giving up (optional; depends on product priority).

4. **Concurrent refresh race:** Multiple API requests might detect 401 and attempt refresh simultaneously. Mitigated by the `refreshInFlight` Promise coordination (see Concurrent refresh guard above).

5. **Cross-tab token invalidation (v1 limitation):** `sessionStorage` is per-browser-tab. If Tapis rotates the refresh token on use (one of the open questions), a refresh in Tab A invalidates Tab B's copy of the refresh token, causing Tab B to hard-fail on its next refresh. This is a new failure mode not present in the current hard-logout behavior (where expiry is uniform across tabs since it's a local timer). **Mitigation for v1:** Accept this as a known limitation with a plan to revisit in v2. Document the limitation in error messages. **Fast-follow for v2:** Implement lightweight cross-tab coordination (e.g., BroadcastChannel to sync refresh state across tabs, or a `storage` event listener) so a successful refresh in one tab is immediately visible to others. See "Alternatives considered" for sketch of this approach.

6. **Session durability vs. security:** Silent refresh extends a session indefinitely as long as the user keeps making requests and the refresh token remains valid. Trade-off: Users expect long-running workflows to "just work," but this also means a stolen session token could be extended. Mitigation: (a) Rely on Tapis's security model for token rotation/revocation; (b) enforce an explicit application-level session ceiling (see "Session ceiling / max refresh duration" above); (c) refresh token is no weaker than the original auth flow.

### Tradeoffs

1. **Complexity:** Adds state management (refresh timer, concurrent guard) to AuthContext. Trade-off: Justifiable because it directly solves a user-facing pain point (mid-workflow logout).

2. **Storage of refresh token:** Currently stored in `sessionStorage` (browser tab-scoped, cleared on tab close). This is more secure than `localStorage` (persistent across tabs) but means each browser tab has its own token. Trade-off: Accepted; tabs are isolated, and sessionStorage is cleared on logout. No change to current approach.

3. **No persistent session:** If the user closes the browser and reopens, they must log in again (refresh token is gone). Trade-off: Expected and accepted; refresh extends a single session, it does not create a persistent login.

### Failure modes

1. **Refresh token revoked server-side:** Refresh call returns 401 or `invalid_grant`. Behavior: Hard logout (existing behavior applied). User must re-login.

2. **Network unavailable during refresh:** Transient error (CORS failure, fetch error). Behavior: Log error; optionally retry with backoff. If retries exhaust, hard logout.

3. **Token refresh response malformed:** Tapis API returns unexpected shape. Behavior: Throw error in `refreshTapisToken()`, caught in AuthContext, hard logout.

4. **System clock far ahead:** Refresh scheduled for past time. Behavior: Timer fires immediately; refresh call may succeed or fail depending on Tapis's validation.

---

## Alternatives considered

### 1. Server-side session management

Upstream API could maintain a session table and extend session TTL on each request. This would eliminate the need for refresh logic.

**Rejected because:**
- Requires API changes and a new database table.
- Upstream API is stateless by design; adding state increases operational complexity.
- The Tapis refresh token is the right primitive for this job (Tapis already manages token lifecycle).

### 2. Keep existing hard-logout, encourage shorter workflows

Continue forcing logout at 4 hours; document that users should break long uploads into shorter sessions.

**Rejected because:**
- Does not solve the user's pain; they want uninterrupted workflows.
- Reduces UX quality and increases support burden.

### 3. Client-side retry on 401, no scheduled refresh

Implement only the fallback mechanism (on-demand refresh on 401), not the scheduled refresh.

**Rejected because:**
- Does not prevent the 401 from occurring mid-workflow.
- Some requests might fail before retry logic kicks in.
- Scheduled refresh is simpler and more predictable.

### 4. Increase TTL via Tapis client registration

Investigate whether Tapis allows setting a custom token TTL at client registration time.

**Current status:** The Upstream registration script (`create_oauth_client.py`) does not include a TTL field, but the Tapis platform operators may have additional mechanisms (e.g., direct API calls or backend configuration) to raise the TTL for specific clients. This mechanism is undocumented rather than confirmed impossible.

**Recommendation:** **In parallel with this implementation,** contact TACC/Tapis platform operators to ask whether the `upstream-develop` and `upstream-prod` OAuth2 clients' access-token TTL can be raised (e.g., from 4 hours to 8–12 hours). This is a cheap, non-blocking parallel inquiry that could reduce the frequency of refreshes needed in practice.

**Not a replacement for silent refresh:** Even if the TTL can be increased, any fixed TTL eventually gets exceeded by a long enough session, so silent refresh is still needed. However, reducing the refresh frequency improves reliability and reduces the number of cross-tab edge cases (see risk #5).

**Rejected as a solo solution because:**
- TTL configuration mechanism is undocumented and may not be available.
- Even if available, there is a maximum TTL beyond which Tapis will not increase (unknown limit).
- Any fixed TTL is eventually exceeded; silent refresh remains the right solution for indefinite session extension.

### 5. Cross-tab coordination (v1 vs. v2 scope)

Address the cross-tab race condition (risk #5) where one tab's refresh invalidates another tab's refresh token.

**v1 approach (current proposal):** Accept cross-tab isolation as a known limitation for the first release. Document it in error messages so users understand why a tab may hard-logout if another tab refreshed. Plan to revisit in v2.

**v2 approach (fast-follow):** Implement cross-tab coordination using:
- **Option A (BroadcastChannel):** After a successful refresh, post the new token/expiry to a `tokenRefresh` BroadcastChannel. Other tabs listen and update their sessionStorage. Simple and modern (supported in all major browsers except IE).
- **Option B (storage event listener):** Have the refresh success path write a flag to sessionStorage, triggering a `storage` event in other tabs. Other tabs listen and re-read the new token. More compatible but less direct than BroadcastChannel.

**Decision for v1:** Use Option A (BroadcastChannel) as the recommended v2 fast-follow. Do not implement in v1 to keep scope manageable, but the architecture should not preclude it (e.g., avoid assumptions that sessionStorage is the only source of truth for tokens).

---

## Test plan

### Manual verification (primary, due to no test framework in upstream-ui)

1. **Happy path: Scheduled refresh succeeds**
   - Log in via username/password.
   - Verify `Tapis-Expires-At` is set in sessionStorage.
   - Advance system clock by ~80% of TTL (e.g., if TTL is 1 hour, advance ~48 minutes).
   - Observe in browser console: `[TapisAuth] Token refreshed successfully`.
   - Verify new token written to sessionStorage.
   - Make an API request; should succeed with new token.
   - Verify next refresh scheduled.

2. **Page reload with existing near-expiry session**
   - Log in via username/password; advance system clock to ~85% of TTL.
   - Reload the page (F5 or Cmd-R).
   - Expected: `checkAuth()` bootstrap effect runs, reads existing tokens and `Tapis-Expires-At` from sessionStorage, schedules a refresh immediately (since 85% > 80% threshold).
   - Observe in console: `[TapisAuth] Token refreshed successfully` (refresh fires right away).
   - Verify new token and expiry written to sessionStorage.
   - Verify user remains logged in (AuthContext.isAuthenticated = true).
   - Verify next refresh scheduled for 80% of the new TTL.

3. **Fallback: On-demand refresh on 401** (if implementing fallback)
   - Log in; allow token to approach expiry without scheduled refresh firing.
   - Manually edit sessionStorage to set `Tapis-Expires-At` to a past timestamp (simulate expiry without waiting).
   - Make an API request.
   - Expected: Request fails with 401 → on-demand refresh triggered → request retried → succeeds.
   - Observe in console: `[TapisAuth] Token refresh failed` (from 401) or success message if fallback works.

4. **Failure: Refresh token revoked**
   - Log in and manually revoke the refresh token on Tapis (if possible in test environment) or mock a 401 response.
   - Wait for scheduled refresh to fire (or advance clock).
   - Observe: `[Auth] Token refresh failed, logging out`.
   - Verify user is logged out (tokens cleared, AuthContext.isAuthenticated = false).
   - Verify "Session expired" message displayed.

5. **Concurrency: Multiple 401s in quick succession** (if implementing fallback)
   - Manually trigger multiple API requests that will 401 at the same time.
   - Observe: Only one refresh attempt (log shows `refreshInFlight` guard working).
   - Both requests eventually succeed with same refreshed token.

6. **Cross-tab isolation (known limitation)**
   - Log in with Token A in Tab 1, allowing same token to load in Tab 2 (copy sessionStorage manually or let both tabs log in to same session).
   - In Tab 1, advance system clock to trigger a refresh. Observe refresh succeeds and a new Token B is written to Tab 1's sessionStorage.
   - In Tab 2, verify that Tab 2 still has Token A in sessionStorage (tabs are isolated; Tab 2 does not automatically see Token B).
   - In Tab 2, advance clock to trigger its own refresh. Verify it attempts to refresh with its own refresh token.
   - Document this as a v1 limitation; fast-follow in v2 to add cross-tab coordination.

7. **Cleanup: Timer cancelled on logout**
   - Log in; verify timer scheduled.
   - Click logout.
   - Verify timer cleared (no further refresh attempts).

### Automated tests (optional, if test framework is added later)

- Jest/Vitest tests for `refreshTapisToken()` with mocked fetch
- Tests for `scheduleTokenRefresh()` with fake timers (`jest.useFakeTimers()`)
- Test concurrent refresh with race conditions

---

## Documentation plan

### Code comments

- Add inline comments to `refreshTapisToken()` explaining the refresh grant type and response shape.
- Add comments in AuthContext explaining why we schedule at 80% TTL instead of waiting until actual expiry.

### CLAUDE.md (upstream-ui)

Add a section to the project CLAUDE.md documenting:
- "Silent token refresh ensures long-running workflows are not interrupted by token expiry."
- "Tokens are refreshed at 80% of TTL; if refresh fails, user is logged out (fallback to existing behavior)."
- "No new test framework is currently in place; verify refresh behavior manually in dev."

### Design spec (this file)

- Keep this spec as the authoritative design document.
- Link to this spec from CLAUDE.md.
- After implementation, update Status to "Implemented" and note any deviations.

### No user-facing documentation needed

- Silent refresh is transparent; no user documentation required.
- If an error occurs, existing error messages ("Session expired") are reused.

---

## Rollout/rollback plan

### Rollout

1. **Feature flag (MANDATORY):** Add an env var `VITE_ENABLE_TOKEN_REFRESH` (default: true) to allow quick disable if issues arise in production. This is a tested revert lever and must be part of the initial deployment checklist.

2. **Deploy to staging:**
   - Build upstream-ui with changes and `VITE_ENABLE_TOKEN_REFRESH=true`.
   - Test refresh behavior in staging environment against test Tapis tenant.
   - Verify upload workflows are not interrupted.
   - Verify fallback to hard logout works when refresh is manually disabled (`VITE_ENABLE_TOKEN_REFRESH=false`).

3. **Deploy to production:**
   - Release to prod with `VITE_ENABLE_TOKEN_REFRESH=true`.
   - Monitor auth-related errors in logs.
   - Monitor token refresh success rate and failure modes.
   - Have a plan to set `VITE_ENABLE_TOKEN_REFRESH=false` and redeploy if critical issues are discovered.

4. **Communicate to users (optional):**
   - If desired, include a note in release notes: "Long-running workflows are no longer interrupted by session timeout; tokens are silently refreshed."

### Rollback

If critical issues occur:

1. **Fast rollback:** Set `VITE_ENABLE_TOKEN_REFRESH=false` and redeploy (users revert to hard-logout behavior without a full app revert).
2. **Full rollback:** Revert upstream-ui to previous deployment (standard CI/CD rollback).
3. Users will return to hard-logout behavior (existing behavior from 2026-07-09 spec).
4. No database migrations or data loss; purely frontend logic.

---

## Open questions

1. **~~Tapis refresh response shape~~ — RESOLVED (see Decisions [2026-08-04d]).** Confirmed against tapipy 25.4.0's bundled OpenAPI spec (`openapi_v3-authenticator.yml`, `TokenResponse` schema) and its reference client implementation (`tapis.py`, `refresh_user_tokens()`):
   - Response is wrapped: `{ result: { access_token: {...}, refresh_token: {...} } }`.
   - `access_token`/`refresh_token` are objects with string fields `access_token`/`refresh_token`, plus `expires_at` (UTC **string**, not numeric) and `expires_in` (integer seconds) — use `expires_in` to compute our own numeric epoch expiry.
   - The refresh call authenticates via **HTTP Basic Auth** (`Authorization: Basic base64(client_id:client_key)`), not client credentials in the JSON body.
   - `refresh_token` is optional in the schema (only `access_token` is required) — confirms Open Question #5 is a real, not hypothetical, concern.

2. **Refresh token TTL — partially resolved.** Confirmed via the same schema that refresh-token TTL is a genuine, independently-configurable **tenant**-level setting (`default_refresh_token_ttl` / `max_refresh_token_ttl`, in seconds, distinct from `default_access_token_ttl`) — it is not fixed at the same ~4h as the access token. However, the actual configured value for the `portals` tenant is only readable via `GET /v3/oauth2/admin/config`, which is restricted to tenant admins; we don't have that access. Still open: get the actual number either by asking TACC/Tapis platform operators, or — requiring no elevated privilege — decode a real, already-issued refresh token's `exp`/`iat` claims during implementation testing (the same technique tapipy itself uses internally in `add_claims_to_token()`) to empirically measure it before relying on it. This remains independent of the 7-day session ceiling decided in [2026-08-04c]: if Tapis's own refresh-token TTL is shorter than 7 days, it remains the effective limit regardless of the app-level cap.

3. **Clock skew handling:** If Tapis rejects a refresh because "token not yet expired," should we implement retry backoff? Or is this edge case rare enough to ignore?

4. **Transient error handling:** How aggressively should we retry network failures during refresh? Current proposal is to fail immediately and log out, but optional exponential backoff could reduce false logouts due to temporary network glitches.

5. **Backward compatibility:** Are there any Tapis configurations or client setups where refresh tokens are not issued? If so, should refresh be optional with a graceful fallback to the existing hard-logout behavior?

6. **Test environment:** What is the best way to test refresh behavior locally? Can we mock the Tapis token endpoint, or do we need a test Tapis tenant with real refresh tokens?

---

## Decisions

### [2026-08-04a] Supersede "no silent refresh" decision from 2026-07-09 spec

**Decision:** Implement silent token refresh using Tapis refresh tokens, replacing the hard-logout-on-expiry behavior documented in the 2026-07-09 spec (lines 138–140).

**Rationale:**
- User pain (mid-workflow logout) is real and blocking data entry workflows (confirmed by production logs).
- Tapis platform already provides refresh tokens; we are not adding external dependencies.
- Implementation is localized to frontend (AuthContext, tapisAuth.ts); no backend changes.
- Refresh extends a single session (does not persist login across browser restarts); security model is unchanged.
- Fallback to hard logout (existing behavior) is still triggered if refresh fails, preserving safety.

**Link to superseded spec:** `/Users/wmobley/Documents/Github/upstream/upstream-docker-pods/docs/design/2026-07-09-unified-ui-tapis-auth-multi-instance.md`, specifically the "Token expiry" section (lines 138–140).

---

### [2026-08-04b] Revisions from 2026-08-04 architect/skeptic/security-reviewer discourse pass

**Changes incorporated:**

1. **Root-cause evidence confirmed:** Updated "User need" to cite production logs (many sequential upload requests across ~4-hour session) rather than relying on assumption. The failure mode is confirmed: "many sequential requests that exceed token TTL" (not "one request with long processing time").

2. **Refresh scheduling wiring fixed:** Changed from imperative calls in login path only to **effect-driven scheduling** keyed off `isAuthenticated` state, mirroring the existing hard-logout timer design. This ensures refresh is scheduled uniformly for all three session-entry paths: fresh login, page reload with existing tokens, and OAuth callback completion. The architect noted the original design would skip the bootstrap path (line 84-123), leaving no refresh for page reloads with near-expiry tokens.

3. **Fail-silent validation requirement added:** `refreshTapisToken()` must **validate the response shape BEFORE updating sessionStorage** and throw on any missing/malformed field. This prevents a silent wipe of all three tokens (where `storeTapisTokens()` clears first, then sets only truthy fields, leaving a zombie session). The implementation now stages validated values and updates atomically (direct sessionStorage.setItem calls instead of reusing the destructive `storeTapisTokens()` pattern).

4. **Concurrent refresh guard rewritten:** Fixed a bug where the guard code referenced an undefined `oldToken` variable. Replaced polling-based approach with a simpler Promise-based coordination: multiple concurrent calls await a single in-flight refresh, all receiving the same result.

5. **Explicit session ceiling required:** Added "Session ceiling / max refresh duration" subsection requiring an explicit application-level cap on total session duration (e.g., refresh-token TTL itself, or 24–48h conservative app-level cap), enforced by recording session start time and checking on each refresh. This prevents unbounded session extension and is a **required decision before implementation**.

6. **Kill switch made mandatory:** Changed `VITE_ENABLE_TOKEN_REFRESH` from optional to a required part of the rollout plan, with fast-rollback strategy (set to false and redeploy to revert to hard-logout behavior).

7. **Cross-tab race condition documented:** Added risk #5 (cross-tab token invalidation if Tapis rotates refresh tokens on use). Accepted as a v1 limitation with a fast-follow plan to implement BroadcastChannel-based cross-tab coordination in v2.

8. **TTL-increase alternative re-litigated:** Clarified that the mechanism is "undocumented, not confirmed impossible" and recommended a parallel, non-blocking inquiry to TACC/Tapis operators about raising the OAuth2 client TTL, without blocking implementation on its outcome.

9. **Test plan expanded:** Added scenario #2 (page reload with near-expiry session) and #6 (cross-tab isolation limitation) to ensure the wiring fix is properly tested.

**Status:** These revisions keep the spec at **Draft** pending final user approval; no implementation has begun.

---

### [2026-08-04c] Session ceiling set to 7 days

- **Decision:** The mandatory application-level session ceiling (required by the security review, see [2026-08-04b] item 5) is set to a fixed **7 days**. Once a session begins (login, page reload with existing tokens, or OAuth callback — recorded as `Tapis-Session-Started-At` in `sessionStorage`), silent refresh will continue working for at most 7 days of elapsed time from that start, after which the next refresh attempt is skipped and `expire()` is called to force re-login, even if the refresh call itself would have succeeded.
- **Reason:** User (wmobley) chose a fixed, predictable app-level limit rather than tying session length to Tapis's own (still-unconfirmed) refresh-token TTL. This resolves the "Session ceiling value" item that was blocking spec approval.
- **Alternatives rejected:**
  - Capping session length at whatever Tapis's refresh-token TTL turns out to be, with no separate app-level cap — rejected because that value is still unknown (Open Question #2) and could be arbitrarily long or short depending on Tapis's own configuration, which is outside this app's control.
  - A shorter conservative cap (24–48h), originally floated by the security reviewer as an example — not chosen; user opted for 7 days instead.
- **User feedback:** "Lets try force relogin in after 7 days" — direct instruction, applied as stated.
- **Impact on implementation:** The 7-day cap is independent of and in addition to whatever Tapis's refresh-token TTL turns out to be (Open Question #2 remains open and still needs confirming — if Tapis's refresh token expires sooner than 7 days, that shorter TTL is still the effective limit in practice). Implementation must record `Tapis-Session-Started-At` at all three session-entry points (fresh login, page reload, OAuth callback) using the same effect-driven wiring as the refresh schedule itself (see [2026-08-04b] item 2), and check elapsed time against the 7-day cap on every scheduled or on-demand refresh attempt before calling `refreshTapisToken()`.

---

### [2026-08-04d] Refresh grant request/response shape verified against tapipy

- **Decision:** Open Question #1 (exact Tapis refresh response shape) is resolved by direct inspection of `tapipy` 25.4.0 (installed locally in `upstream-docker-pods/.venv`), specifically its bundled OpenAPI spec (`tapipy/resources/openapi_v3-authenticator.yml`, `TokenResponse`/`NewToken` schemas under `/v3/oauth2/tokens`) and its reference client implementation (`tapipy/tapis.py`, `refresh_user_tokens()` / `add_claims_to_token()`). This is authoritative — it's the actual working Tapis SDK, not documentation or guesswork. Confirmed:
  - Response wrapper: `{ result: { access_token: {...}, refresh_token: {...} } }`.
  - `access_token`/`refresh_token` are objects: `{ access_token | refresh_token: <JWT string>, expires_at: <UTC string, NOT numeric>, expires_in: <integer seconds>, jti }`. Use `expires_in` to compute a numeric epoch expiry (`Date.now()/1000 + expires_in`) — the spec's earlier code sketch validated `expires_at` as a number, which would always fail; corrected.
  - The refresh grant authenticates via **HTTP Basic Auth** (`Authorization: Basic base64(client_id:client_key)`), not client credentials in the JSON body (unlike the authorization_code exchange in `exchangeOAuthCode()`). Corrected in the `refreshTapisToken()` sketch.
  - `refresh_token` is optional in the schema (only `access_token` is required), confirming Open Question #5 is a real risk, not hypothetical.
- **Reason:** Implementation was explicitly blocked on this verification (see [2026-08-04b] item 3 / prior "Unconfirmed and blocking implementation" note in API/schema changes). Using the installed SDK's own spec and reference code is more reliable than reverse-engineering from partial public docs.
- **Alternatives rejected:** Attempting a live test call against the production `portals.tapis.io` tenant with real credentials — rejected as an unnecessary external/production action when the bundled SDK already provides an authoritative, offline answer.
- **User feedback:** User asked to "verify them" (the two blocking open questions) after reviewing the discourse synthesis; this entry and [2026-08-04e] are the result.
- **Impact on implementation:** `refreshTapisToken()`'s code sketch (Proposed design → New function) and the "API/schema changes" section are both updated to match. This also surfaced a **pre-existing, unrelated bug**: `exchangeOAuthCode()` in `tapisAuth.ts` (the pure-frontend OAuth2-callback path, separate from this feature) read `refreshTokenObj.access_token` instead of `.refresh_token`, and treated `expires_at` as numeric when the schema says it's a string — meaning that path never correctly captured a usable refresh token or expiry. **Fixed 2026-08-04** (user approved fixing it immediately as a standalone trivial-tier change rather than deferring to this feature's implementation): `refreshTokenObj.refresh_token` used, and `expiresAt` now computed from `accessTokenObj.expires_in`. Verified with `tsc --noEmit` (clean, no new errors). Logged as `upstream-ui/.wolf/buglog.json` bug-061.

### [2026-08-04e] Refresh-token TTL partially verified — actual value still unknown

- **Decision:** Open Question #2 is downgraded from "fully open" to "partially resolved, one specific fact still needed." Confirmed via the same `tapipy` OpenAPI spec that refresh-token TTL (`default_refresh_token_ttl` / `max_refresh_token_ttl`) is a genuine, independently-configurable **tenant**-level setting, separate from `default_access_token_ttl` — i.e., there is no schema-level reason to assume it's also stuck at ~4 hours. However, reading the actual configured value for the `portals` tenant requires `GET /v3/oauth2/admin/config`, which the schema marks "restricted to Tenant admins" — we do not have that access.
- **Reason:** Could not fully resolve without either tenant-admin credentials (which we don't have and shouldn't request just for this) or a live authenticated call.
- **Alternatives rejected:** Attempting to authenticate with real user credentials against production Tapis solely to inspect a token's claims — deferred rather than done unilaterally, since it's a live action against a production auth system and should happen naturally during implementation/testing rather than as a standalone probing step now.
- **User feedback:** none yet on this specific remaining gap.
- **Impact on implementation:** Before or during implementation, decode a real, already-issued refresh token's `exp`/`iat` claims (same technique `tapipy` uses internally) to empirically measure the actual TTL — this requires no elevated privilege, just a normal login. This is independent of the 7-day session ceiling ([2026-08-04c]): if the measured refresh-token TTL is shorter than 7 days, it remains the binding limit regardless of the app-level cap.

---

### [2026-08-04f] Live test: password grant issues NO refresh token — feasibility question raised, not yet resolved

- **Finding:** User (wmobley) ran `scripts/check_tapis_token_ttls.py` against the live `portals` tenant using the `password` grant (the same grant `TapisAuthClient.authenticate()` in `app/tapis/client.py` uses for the existing username/password login form, `POST /api/v1/token`). Result: **no refresh token was returned at all.** The access token's claims also did not include an `iat` claim (only `exp`), which the diagnostic script didn't anticipate — irrelevant here since there was no refresh token to measure anyway, but noted for anyone reusing that script.
- **Why this matters:** This is a real tenant-policy answer to Open Question #5, not a script bug. Many Tapis/OAuth2 tenants deliberately restrict refresh-token issuance to the `authorization_code` grant and exclude `password` as legacy/no-refresh. If that's what's happening here, **silent refresh as designed provides zero benefit for any user authenticated via the username/password login form** — there is no refresh token in hand to use, independent of implementation quality. It remains unverified whether the OAuth2 `authorization_code` grant (the "unified UI" login path via `initiateOAuthLogin()`/`exchangeOAuthCode()` in `tapisAuth.ts`) behaves differently and does issue a refresh token — this test only exercised the `password` grant.
- **Reason password-grant is a plausible dead end here:** password grant is widely treated as legacy/deprecated in OAuth2, and platforms commonly gate refresh-token issuance to more modern flows for security reasons (a long-lived refresh token paired with a password grant that transmits raw credentials is a weaker combination than pairing it with authorization_code, which never transmits a password to the client at all).
- **User feedback:** User was offered three ways to resolve the open question (self-test the OAuth2 authorization_code path in the browser, ask TACC/Tapis operators directly, or proceed assuming authorization_code works and scope the feature to OAuth2-login users only) and chose to **test the authorization_code path themselves** by logging into the deployed Upstream UI via the OAuth2/unified-UI login and inspecting `sessionStorage['Tapis-Refresh-Token']` in browser devtools.
- **Impact on implementation:** **Blocking.** Do not move this spec to Approved, and do not begin implementation, until this is confirmed one way or the other:
  - If `authorization_code` **does** issue a refresh token: scope this feature explicitly to users authenticated via the OAuth2 unified-UI login path only. Users still on the legacy username/password form keep today's hard-logout-on-expiry behavior (accurately reflects that there's nothing to refresh for them) — update "User need" and "Definition of success" to state this scope limitation explicitly rather than implying it fixes the problem for all users.
  - If `authorization_code` **also** returns no refresh token: this design does not work as scoped for any current login path, and the next real option is asking TACC/Tapis operators whether the tenant's `allowable_grant_types`/refresh-issuance policy can be changed for either grant type — this becomes a platform-configuration question, not a frontend implementation question, and the spec would need to be substantially rethought (or paused pending that platform-level answer).
- **Security note (out of band, not part of this decision but recorded for completeness):** the live credentials used for this test were pasted directly into the chat transcript. The user was advised immediately to rotate that TACC password; no credential value was stored, logged, or repeated in this repository as part of this work.

---

## User feedback / decisions

- **2026-08-04:** User (wmobley) reviewed the architect/skeptic/security-reviewer discourse findings and set the session ceiling to 7 days ("Lets try force relogin in after 7 days"). See Decisions entry [2026-08-04c].
- **2026-08-04:** User asked to verify Open Questions #1 (response shape) and #2 (refresh-token TTL) against Tapis directly. #1 is now resolved via tapipy's bundled SDK/spec ([2026-08-04d]), which also surfaced a pre-existing unrelated bug in `exchangeOAuthCode()` needing a decision on whether to fix now or alongside implementation. #2 is partially resolved — the TTL is confirmed independently configurable, but the actual number requires either tenant-admin access we don't have, or empirical measurement from a live refresh token during implementation ([2026-08-04e]).
- **2026-08-04:** User ran the live TTL-check script against the password grant; no refresh token was issued at all ([2026-08-04f]). This raises a real feasibility question for the password-grant login path specifically. User chose to self-test whether the OAuth2 authorization_code ("unified UI") login path fares differently, by checking `sessionStorage['Tapis-Refresh-Token']` in browser devtools after logging in that way. **Spec approval remains blocked pending that result.**

---

## Implementation notes

- Before implementation begins, verify the Tapis refresh response shape against tapipy or a live endpoint (open question #1).
- Consider whether to implement the on-demand refresh (401 interception) fallback in v1 or defer to v2 based on complexity and test coverage.
- Ensure token masking is applied consistently in all debug logs to avoid accidental exposure.

