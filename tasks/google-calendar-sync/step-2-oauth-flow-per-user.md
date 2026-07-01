# Step 2 — Per-user OAuth flow (Google Calendar scope)

**Goal:** The employee clicks Connect on the Integrations page →
Google's OAuth consent → they land back on the CRM with their Calendar
tokens stored + status "Connected".
**Status:** COMPLETED
**Depends on:** Step 1 (schema).

---

## Scope

### OAuth surface

Reuses the same Google OAuth client the Ads flow uses (existing
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars) but with:

- New scope: `https://www.googleapis.com/auth/calendar.events`
- Also request `openid email profile` so we can populate
  `google_email` + `google_user_id` on the token row
- Separate authorize URL prefix `/api/v1/integrations/google-calendar/*`
  so the callback doesn't collide with the Ads callback
- **State parameter carries the target `user_id`** — this is what
  makes the flow per-user rather than per-org. The state is HMAC-
  signed so an attacker can't swap user ids.

### Endpoints

- `GET /api/v1/integrations/google-calendar/authorize` — starts the
  flow for the currently-authenticated user. Redirects to Google.
- `GET /api/v1/integrations/google-calendar/callback?code=...&state=...`
  — Google redirects here. Verifies state HMAC + state's `user_id`
  matches the JWT's user_id + exchanges code for tokens + writes the
  token row + redirects to `/user/integrations?status=connected`.
- `POST /api/v1/integrations/google-calendar/disconnect` — deletes the
  token row + calls Google's `/revoke` endpoint. Returns 204.
- `GET /api/v1/integrations/google-calendar/status` — returns
  `{connected: bool, google_email: str | null, last_error: str | null,
  last_synced_at: str | null}` for the current user. Drives the
  integrations card.

### Token refresh helper

`google_calendar/oauth.py` exposes `async get_valid_access_token(
session, user_id) -> str` that:

1. Reads the row for the user
2. If `access_token_expires_at` is >60s away, decrypts + returns the
   cached access token
3. Otherwise calls Google's `/token` endpoint with the refresh token,
   updates the row with the new access token + expiry, returns it
4. On `invalid_grant` (revoked): marks the row `status='revoked'`,
   raises `GoogleCalendarNotConnected` — sync callers catch + skip

Callers throughout the sync path use `get_valid_access_token` — never
touch the raw refresh token directly.

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/google_calendar/oauth.py` | **NEW** |
| `API/src/app/core/integrations/google_calendar/router.py` | **NEW** — 4 endpoints |
| `API/src/app/core/integrations/google_calendar/service.py` | **NEW** — token CRUD + state HMAC |
| `API/src/app/core/integrations/google_calendar/data_access.py` | **NEW** — row read/write helpers |
| `API/src/app/core/integrations/router.py` | edit — mount the sub-router |

**~5 files, ~350 lines.**

## Verify

- Log in as Ajay → hit `/api/v1/integrations/google-calendar/authorize`
  → land on Google's consent screen with the calendar scope listed
- Grant → land back on `/user/integrations?status=connected` → status
  endpoint returns `connected=true` with `google_email='ajaygogane224@gmail.com'`
- Disconnect endpoint 204s → status endpoint returns `connected=false`
- Attempting the callback with a tampered state param 400s

## Self-check

`core/integrations/google_calendar/` follows the layered layout
(router / service / data_access / oauth). Only service.py touches
transactions. Router calls service. State HMAC verified server-side.
No token stored plaintext. Stop-report.
