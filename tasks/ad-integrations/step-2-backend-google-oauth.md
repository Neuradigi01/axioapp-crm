# Step 2 — Backend: Google Ads OAuth flow

**Goal:** Implement the Google OAuth 2.0 flow that lets an Owner connect a Google Ads account to their org. Includes the authorize redirect, callback handler, token exchange, persistence (encrypted via Step 1's crypto), a token-refresh helper, and an API-client wrapper that uses the stored credentials to list the org's Google Ads accounts and Lead Forms.
**Track:** Ad Integrations
**Status:** Pending
**Depends on:** Step 1 (`integrations` table + crypto), `.env` populated with `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`.

---

## Scope

In-scope:

- `core/integrations/google/oauth.py`:
  - `start_authorize(org_id, actor) -> str` — returns the Google consent URL with a signed state (containing `org_id`, `actor_id`, `nonce`, `expires_at`).
  - `handle_callback(code, state) -> Integration` — verifies state, exchanges code for tokens, fetches profile (email), upserts the integration row.
- `core/integrations/google/api_client.py`:
  - `GoogleAdsClient(integration)` wrapping `google-ads` SDK (or REST API if SDK is too heavy — decision in plan).
  - Auto-refreshes access token using stored refresh token; updates the row on rotation.
- `core/integrations/google/sync_forms.py`:
  - `list_accessible_accounts() -> list[GoogleAdsAccount]` — calls `customers.listAccessibleCustomers`.
  - `list_lead_forms(customer_id) -> list[GoogleLeadForm]` — extracts from `extension_feed_items`.
- Router endpoints under `/api/v1/integrations/google`:
  - `GET /authorize` → 302 redirect to Google consent.
  - `GET /callback` → handles Google's redirect; on success, redirects back to `/user/settings/integrations?status=google_connected`.
  - `GET /accounts` → list of accounts (admin-auth).
  - `GET /accounts/{customer_id}/forms` → list of lead forms (admin-auth).
- Env vars: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_ADS_DEVELOPER_TOKEN`.
- Audit events: `integration.google.connected`, `integration.google.disconnected` (the latter wired in Step 1's generic disconnect — just provider-tag the existing event).
- Tests with mocked HTTP responses for token exchange + accounts/forms listing.

Out of scope:

- Webhook receiver — Step 3.
- Form selection persistence — Step 4/7 (lives in `integration_subscriptions` table introduced for Meta).
- Field mapping — Step 8.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/google/__init__.py` | created |
| `api/src/app/core/integrations/google/oauth.py` | created |
| `api/src/app/core/integrations/google/api_client.py` | created |
| `api/src/app/core/integrations/google/sync_forms.py` | created |
| `api/src/app/core/integrations/router.py` | modified — include Google subrouter |
| `api/src/app/core/integrations/google/router.py` | created — Google-specific routes |
| `api/src/app/shared/config.py` | modified — add `GOOGLE_OAUTH_*` settings |
| `.env.example` | modified — add Google OAuth vars |
| `api/pyproject.toml` | modified — add `google-ads` dep OR document REST decision (see plan) |
| `api/tests/test_google_oauth.py` | created |

**10 files.** At rule-8 ceiling.

## Plan

1. **SDK vs REST decision:** the `google-ads` Python SDK is heavyweight (~50 MB transitive deps, GRPC, protobufs). For our two endpoints (`listAccessibleCustomers`, `extension_feed_items` query) the REST API via `httpx` is sufficient. **Decision: REST via httpx.** Document in `api_client.py` module docstring.
2. `oauth.py`:
   - State signing: `itsdangerous.URLSafeTimedSerializer` with `INTEGRATIONS_ENCRYPTION_KEY` as the secret. `max_age=600` seconds.
   - `start_authorize`: builds the consent URL with `scope=https://www.googleapis.com/auth/adwords` + `offline access` + `prompt=consent` (forces refresh-token issuance).
   - `handle_callback`: verifies state freshness, POSTs to `https://oauth2.googleapis.com/token` for token exchange, fetches profile via `https://www.googleapis.com/oauth2/v2/userinfo` to get the email for `account_label`, calls `service.upsert(...)`.
3. `api_client.py`:
   - `class GoogleAdsRestClient` with `__init__(integration)` and a `_get_access_token()` method that checks `integration.token_expires_at`; if expired (or within 60s of expiry), refreshes via the refresh token, updates the row.
   - All HTTP calls go through a single `_request(method, url, **kwargs)` helper that adds `Authorization: Bearer ...` + `developer-token: {GOOGLE_ADS_DEVELOPER_TOKEN}` + `login-customer-id` (manager account if applicable; for v1 we accept the user's primary customer as login-customer).
4. `sync_forms.py`:
   - `list_accessible_accounts()`: GET `https://googleads.googleapis.com/v15/customers:listAccessibleCustomers`. Returns `[{customer_id, name}]`.
   - `list_lead_forms(customer_id)`: POST `https://googleads.googleapis.com/v15/customers/{customer_id}/googleAds:searchStream` with GAQL `SELECT extension_feed_item.lead_form_field, extension_feed_item.id FROM extension_feed_item WHERE extension_feed_item.extension_type = 'LEAD_FORM'`. Returns parsed forms.
5. Wire endpoints in `google/router.py`. Permission gate on admin endpoints.
6. Tests: mock the OAuth + Google Ads API HTTP calls (`respx` for httpx).

## Tests

`api/tests/test_google_oauth.py`:

- **Authorize URL shape:** `start_authorize` returns a URL pointing to `accounts.google.com/o/oauth2/...` with `client_id`, `redirect_uri`, `scope`, `state`, `access_type=offline`, `prompt=consent`.
- **State integrity:** state decodes to original org/actor. Tampered state raises.
- **Callback happy path (mocked):** mock token exchange to return `{access_token, refresh_token, expires_in}`, mock userinfo to return `{email: "asha@example.com"}`. Call `handle_callback(code, state)`. Verify integration row created with status `connected` and tokens encrypted.
- **Callback rejects expired state:** older than 10 min → 400.
- **Token refresh:** mock an `Integration` row with `token_expires_at` in the past. Call `_get_access_token()`. Verify token-refresh POST sent. Verify the row's `access_token_enc` and `token_expires_at` updated.
- **List accessible accounts:** mock the API. Verify response shape.
- **List lead forms:** mock the searchStream response. Verify parsing.
- **Permission gate:** Employee → 403 on admin endpoints.

## Smoke

```powershell
# Set Google OAuth vars in .env (dev client from your Google Cloud Console project)
# GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
# GOOGLE_OAUTH_CLIENT_SECRET=...
# GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/integrations/google/callback
# GOOGLE_ADS_DEVELOPER_TOKEN=...

docker-compose restart api

# As Owner, hit the authorize endpoint via the browser
# (must be logged in to the CRM admin first; this endpoint reads the JWT)
# http://localhost:8000/api/v1/integrations/google/authorize
# → 302 to Google consent screen
# → grant → redirected back to /user/settings/integrations?status=google_connected

# Confirm via API
curl http://localhost:8000/api/v1/integrations -H "Authorization: Bearer $token"
# Expect: [{provider:"google_ads", status:"connected", account_label:"asha@…"}]

curl http://localhost:8000/api/v1/integrations/google/accounts -H "Authorization: Bearer $token"
# Expect: list of accessible customers

# Pick one and list forms
curl http://localhost:8000/api/v1/integrations/google/accounts/123-456-7890/forms -H "Authorization: Bearer $token"
# Expect: list of lead forms (may be empty if none configured in Google Ads)
```

## Risks

- **Google OAuth app verification:** unverified apps are limited to 100 users + show a scary warning. Production launch needs verification — typically 1–2 weeks of back-and-forth with Google's review team. Start the verification now, separately from this code; the code works against the unverified app for dev/test.
- **Developer Token approval:** the Google Ads API requires a Developer Token tied to a Google Ads manager account. Apply at https://developers.google.com/google-ads/api/docs/first-call/dev-token. Test mode works without approval; production traffic needs Basic Access tier.
- **REST API version drift:** v15 today; pin in `api_client.py`. New versions land every ~2 months; upgrades are a separate small task.
- **`login-customer-id` ambiguity:** if the user is on a manager account managing multiple sub-accounts, the API requires `login-customer-id` header pointing at the manager. For v1, default to the first accessible account; if the user has a manager structure, document the limitation and revisit.
- **Refresh token rotation race:** if two requests trigger refresh simultaneously, both write the row. Last-writer-wins is acceptable for v1; a Redis lock per integration is the proper fix later.

## Rollback

Delete the new files. Revert router include + config + .env.example. Existing integration rows remain but cannot authenticate without the client code; effectively disabled.
