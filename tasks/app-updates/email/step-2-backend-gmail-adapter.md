# Step 2 — Backend: Gmail adapter (OAuth + history-based sync + send)

**Goal:** Implement the Gmail provider: OAuth connect/refresh, initial 30-day backfill, incremental history-based sync, and outbound send via the user's own Gmail account. Plugs into the shared scaffolding from Step 1.
**Status:** COMPLETED — `core/email/gmail/` sub-package shipped with seven files (`__init__.py` which side-effect-registers `GmailProvider` into the Step 1 OAuth registry; `oauth.py` with `GmailProvider` implementing `authorize_url` / `exchange_code` / `refresh` + `fetch_userinfo` for email_address+display_name; `client.py` with `GmailClient` httpx wrapper that calls `email_service.refresh_if_expired` before each request and raises `GmailHTTPError` on 4xx so callers can branch on 404; `sync.py` with `backfill(days=30)` walking `users.messages.list` with `newer_than:Nd` query + `sync_incremental` walking `users.history.list` from the stored cursor — both extract From/To/Cc/Bcc, do case-insensitive lookup against `contacts.email` via the existing TenantScoped ORM filter, and return `MatchedMessage` records with the resolved `contact_id` + headers; `send.py` with optimistic-increment-then-rollback daily cap enforcement against `account.daily_sent_count` (soft 200 warns, hard 500 raises `DailyCapExceeded(429)`); `push.py` with `watch_if_configured` (no-op when Pub/Sub topic env var is empty — graceful fallback to Step 4's poll), `stop_watch_quiet` (idempotent disconnect teardown), `verify_oidc_jwt` (Google JWKS-backed validation via python-jose, audience + issuer + email claim check + JWKS cache with TTL + force-refresh on signature mismatch), `decode_pubsub_message` (base64 + JSON envelope parser), and `find_account_by_email` (raw SQL bypassing the tenant filter, same pattern as `integrations.get_by_webhook_secret`); `router.py` exposing `GET /authorize` (returns the consent URL as JSON for SPA navigation), `GET /callback` (verifies state, exchanges code, fetches userinfo, upserts via Step 1's service, optionally registers Pub/Sub watch + seeds sync_cursor, redirects to `/user/settings/email-accounts?status=gmail_connected`), and `POST /push` (verifies OIDC JWT, decodes payload, resolves account, logs — Step 4 will enqueue Celery sync task here)). Step 1's `core/email/router.py` extended to (a) `include_router(gmail_router)` and (b) call provider-specific `stop_watch_quiet` BEFORE token nulling on disconnect via a `_teardown_provider_watch` dispatch. `config.py` + `.env.example` extended with `GOOGLE_GMAIL_REDIRECT_URI` (default `http://localhost:8000/api/v1/email/gmail/callback`), `GOOGLE_GMAIL_PUBSUB_TOPIC` (optional — empty disables push), `GOOGLE_GMAIL_PUBSUB_SA_EMAIL`, and `EMAIL_DAILY_SOFT_CAP` / `EMAIL_DAILY_HARD_CAP` overrides. Tests cover: GmailProvider authorize-URL composition + 503 without client + token-endpoint roundtrip + 400 on Google error + refresh-without-refresh-token semantics; GmailClient bearer-after-refresh + 4xx-raises-GmailHTTPError + disconnected-account-409-at-init; sync.backfill matched-collection + multi-page walk + 404-skip; sync.sync_incremental history-walk + no-cursor RuntimeError; send hard-cap blocks (counter unchanged, no Gmail call) + happy path increments + Gmail-failure rolls counter back + near-soft-cap flag; push.decode_pubsub_message happy/missing-message/non-b64/missing-inner-fields; address-extraction regex for bracketed/bare/comma-list/case-folded forms. **Notable adaptations:** (a) **OAuth client reused** — same `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` as the Google Ads track; different redirect URI (`GOOGLE_GMAIL_REDIRECT_URI`) keeps the callbacks unambiguous and avoids requiring a second OAuth client in the same GCP project; (b) **state signing reused** — uses Step 1's `oauth.issue_state` / `verify_state` HMAC primitives (JWT_SECRET_KEY-signed, 10-min TTL) rather than spec'd ad-hoc state machinery; (c) **Pub/Sub is OPTIONAL** — when `GOOGLE_GMAIL_PUBSUB_TOPIC` is empty, `watch_if_configured` no-ops and the `/push` endpoint returns 503; the mailbox is synced via Step 4's 60-second poll fallback (acknowledged in the manual setup checklist); (d) **sync primitives RETURN matched messages** rather than persisting — Step 5's conversations email adapter will plug into this; keeps Step 2 standalone-testable without a fake conversations module; (e) **no `respx` dependency added** — tests use a `_StubHttp` stand-in matching the existing `test_integrations_table.py` convention; (f) **disconnect teardown via dispatch helper** in Step 1's router rather than embedding `stop_watch_quiet` into the generic service.disconnect — keeps `core/email/service.py` provider-agnostic. Smoke verified: `GET /api/v1/email/gmail/authorize` with Owner JWT returns a fully-formed Google consent URL (correct client_id, scopes `gmail.modify userinfo.email userinfo.profile openid`, `access_type=offline`, `prompt=consent`, HMAC-signed state, redirect to `/api/v1/email/gmail/callback`); `POST /push` returns 503 with topic unset; `GET /callback` with missing params redirects 302 to `http://localhost:4200/user/settings/email-accounts?status=gmail_error&reason=missing_params`; Step 1's `GET /accounts` still 200 (no regression). **OAuth verification clock is NOT started** — the `gmail.modify` scope is restricted and needs Google CASA audit (4-6 weeks); dev works today against test users on the existing OAuth consent screen.
**Track:** App Updates → Email
**Depends on:** Step 1 (`email_accounts` table + OAuth scaffolding). External: Google Cloud project + OAuth client + Gmail API enabled.

---

## Scope

In-scope:

- `core/email/gmail/` sub-package:
  - `client.py` — thin HTTP wrapper over `https://gmail.googleapis.com/gmail/v1/users/me/...`. Uses `httpx.AsyncClient`. Auto-refreshes the access token via `service.refresh_if_expired` from Step 1.
  - `sync.py` — `backfill(account, days=30)` and `sync_incremental(account)`. Incremental uses Gmail's `users.history.list?startHistoryId=…`.
  - `send.py` — `send(account, raw_mime: bytes) -> message_id`. Posts to `users.messages.send` with `raw` field (base64url-encoded MIME).
  - `push.py` — Gmail push notification setup: calls `users.watch` on connect, handles incoming Pub/Sub webhooks at `POST /api/v1/email/gmail/push`.
  - `__init__.py` — registers the `gmail` provider into the OAuth registry from Step 1.
- OAuth scopes: `https://www.googleapis.com/auth/gmail.modify` (read + send + label), `userinfo.email`, `userinfo.profile`.
- `OAuthProvider` implementation: `authorize_url`, `exchange_code`, `refresh`.
- Connect endpoint: `GET /api/v1/email/gmail/connect` (kicks OAuth) + `GET /api/v1/email/gmail/callback`.
- Pub/Sub push subscription setup on connect, teardown on disconnect.

Out of scope:

- The actual sync daemon (Step 4) — this step only builds the primitives.
- Conversations channel adapter (Step 5).
- Tracking pixel injection (Step 8).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/email/gmail/__init__.py` | created — provider registration |
| `api/src/app/core/email/gmail/client.py` | created |
| `api/src/app/core/email/gmail/sync.py` | created |
| `api/src/app/core/email/gmail/send.py` | created |
| `api/src/app/core/email/gmail/push.py` | created |
| `api/src/app/core/email/router.py` | modified — add `/gmail/connect`, `/gmail/callback`, `/gmail/push` |
| `.env.example` | modified — add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_PUBSUB_TOPIC` |
| `api/tests/test_email_gmail.py` | created |

**8 files.**

## Plan

1. Configure Google Cloud project + OAuth client (manual setup checklist — link to `manual-google-gmail-setup.md` if you split it out).
2. `client.py`: `GmailClient(account)` with methods `list_history(start_id)`, `list_messages(query)`, `get_message(id, format='raw')`, `send_message(raw)`, `watch(topic)`, `stop_watch()`. Each method calls `refresh_if_expired` first.
3. `sync.py`:
   - `backfill(account, days=30)`: list messages with query `newer_than:30d`, fetch each in `format=metadata` first to extract headers, match `from/to/cc` against `contacts.email` (case-insensitive). For matched messages, fetch `format=raw` and persist via Step 5's conversation adapter.
   - `sync_incremental(account)`: call `users.history.list?startHistoryId=account.sync_cursor&historyTypes=messageAdded&historyTypes=messageDeleted`. Process each event. Update `sync_cursor` to the new `historyId`.
4. `send.py`: `send(account, raw_mime)` builds the JSON payload `{"raw": base64url(raw_mime), "threadId": optional}` and POSTs to `users.messages.send`. Returns the new `message.id`. Increments `account.daily_sent_count`.
5. `push.py`:
   - On connect: call `users.watch` with the Pub/Sub topic from env. Store the returned `historyId` as the initial `sync_cursor`. Schedule a Celery task to renew the watch every 6 days (Gmail expires watches at 7 days).
   - On disconnect: call `users.stop()`.
   - Webhook handler at `POST /email/gmail/push`: validates the Pub/Sub JWT, looks up the account by `emailAddress` in the payload, enqueues a sync task.
6. Router: `/gmail/connect` returns the authorize URL with HMAC-signed `state`. `/gmail/callback` validates state, exchanges code, fetches `userinfo.email`, upserts an `email_accounts` row, kicks off backfill via Celery.

## Tests

`api/tests/test_email_gmail.py` (uses `respx` to mock Gmail HTTP):

- **OAuth roundtrip:** `state` validates; mocked code exchange returns tokens; account row created with encrypted tokens, `provider='gmail'`, `sync_state='backfilling'`.
- **Token auto-refresh:** mock 401 on first request, mock refresh endpoint, retry succeeds.
- **Incremental sync:** seed `sync_cursor=12345`. Mock `history.list` returning 2 added + 1 deleted message. Verify 2 inbound calls to message-fetch, conversation rows created (matched to a seeded contact). Cursor advances.
- **Sync skips unmatched:** mock message with `from` not in contacts → no row persisted.
- **Send:** mock `messages.send` returning `{"id":"xyz"}`. Send call returns the id; `daily_sent_count` increments.
- **Daily cap enforced:** when `daily_sent_count >= soft_cap`, send raises `DailyCapExceeded`. (Soft cap = 200 default; configurable in Step 5.)
- **Push webhook:** valid JWT + known email → enqueues sync task. Invalid JWT → 401.
- **Disconnect:** zeroes tokens, calls `users.stop`, audit event emitted.

## Smoke

```powershell
# Pre-req: GOOGLE_CLIENT_ID/SECRET set in api/.env
docker exec template_api-api-1 uv run pytest tests/test_email_gmail.py -v

# Browser flow (manual):
# 1. Open http://localhost:4200/user/settings/email-accounts (after Step 9)
#    — or directly: GET /api/v1/email/gmail/connect → follow returned URL
# 2. Consent in Google
# 3. Land back on /api/v1/email/gmail/callback?code=…
# 4. List accounts: curl http://localhost:8000/api/v1/email/accounts → 1 row
```

## Risks

- **Gmail OAuth verification (scope: `gmail.modify`).** Restricted scope. Requires Google CASA audit. Unverified app = 100-user cap + scary warning screen. **External clock: 4–6 weeks.** Kick off the OAuth app review the day this step starts.
- **Pub/Sub setup complexity.** Push needs a GCP Pub/Sub topic + subscription + service-account credentials for the topic to receive Gmail's pushes. Document setup in `manual-google-gmail-setup.md`. Fallback: if Pub/Sub isn't configured, fall back to 60-second poll via Step 4's daemon.
- **History ID expiry.** If a mailbox is idle for >7 days and the watch expires, `historyId` may be unusable on next sync — Gmail will return 404. Handle by triggering a full re-backfill on 404 and resetting `sync_cursor`.
- **Quota: 1B requests/day.** Not a real concern at single-customer scale. Document for ops.

## Rollback

Delete the new files. Revert router + `.env.example` edits. Existing connected accounts stop syncing but rows remain. Re-running `users.stop` on already-stopped watches is a no-op.
