# Step 3 — Backend: Microsoft Graph adapter (OAuth + delta sync + send)

**Goal:** Microsoft 365 / Outlook provider. Same surface as Gmail (OAuth, backfill, incremental, send) but using Microsoft Graph + delta tokens + change notifications instead of Gmail history + Pub/Sub.
**Track:** App Updates → Email
**Status:** COMPLETED — `core/email/microsoft/` sub-package shipped with seven files. `__init__.py` side-effect-registers `MicrosoftProvider` into the Step 1 OAuth registry on import (same pattern as Gmail). `oauth.py` ships `MicrosoftProvider` implementing the Protocol (`authorize_url` builds `login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize` with `prompt=consent` + `offline_access` scope for refresh-token guarantee; `exchange_code` POSTs form-encoded to the token endpoint; `refresh` **propagates the rotated refresh token** — critical Microsoft-vs-Google difference, the caller's `service.refresh_if_expired` already persists it via the rotation check in Step 1) + `fetch_userinfo` hitting `/v1.0/me`. `client.py` ships `GraphClient` httpx wrapper with `list_messages` ($filter/$select/$top), `list_messages_delta` (initial delta seed), `get_absolute` (follows `@odata.nextLink` / `deltaLink` URLs exactly as Graph emits them — no param tampering), `get_message_raw` ($value bytes endpoint), `send_raw` (sendMail with text/plain b64), `create_subscription` + `renew_subscription` + `delete_subscription`. Built-in 429 backoff: honours `Retry-After` header (or 30s default), max 2 retries before raising `GraphHTTPError(429)`. Disconnected accounts rejected at init (409). `sync.py` ships `backfill(days=30)` which (Phase 1) filter-walks `/me/messages?$filter=receivedDateTime ge {iso}` with `nextLink` pagination, then (Phase 2) seeds a delta cursor by walking `/me/messages/delta` until `@odata.deltaLink` (cap 50 pages to avoid runaway). `sync_incremental` walks the stored deltaLink chain; on 410 (`delta_link_expired=True`) the caller drops back to backfill. Both extract from/to/cc/bcc participants and case-insensitively match against `contacts.email` for the active tenant; return `MatchedMessage(graph_message_id, graph_conversation_id, headers, matched_contact_id)`. `_extract_headers` reconstructs an rfc-822-ish dict (subject, message-id, from, to, cc, bcc, date) from Graph's normalised shape + stashes `conversationId` under `x-graph-conversation-id` so Step 5's threading helper can fall back to it. `send.py` mirrors Gmail's daily-cap pattern with optimistic-increment-then-rollback against `account.daily_sent_count`. **`provider_message_id` is None** — Graph's sendMail returns 202 with no message id; Step 5 uses the outbound MIME's Message-ID header to correlate (documented in send.py docstring). `webhook.py` ships `subscribe_if_configured` (no-op when `MICROSOFT_GRAPH_WEBHOOK_URL` empty — graceful fallback to Step 4's poll), `unsubscribe_quiet`, `renew_subscription` (PATCH expirationDateTime to now+65h), `decode_notification` (validates envelope shape, returns the `value` array of events), `assert_client_state` (constant-time HMAC compare), `find_account_by_subscription_id` (raw SQL bypassing tenant filter, mirrors Gmail's `find_account_by_email` and integrations' `get_by_webhook_secret` pattern), and `client_state_for(account_id)` (deterministic HMAC-SHA256 of account id under JWT_SECRET_KEY — no extra DB column needed, rotates with the signing key). `router.py` exposes `GET /authorize` (returns consent URL JSON), `GET /callback` (verifies state, exchanges code, fetches `/me`, upserts via Step 1's service, optionally subscribes + stores subscription id in `sync_cursor`, redirects to `/user/settings/email-accounts?status=microsoft_connected`), `GET /webhook?validationToken=...` (echoes the token as plain text — Graph subscription-validation handshake, no signature check since the request type is the only proof), `POST /webhook` (verifies clientState per-event, dedupes by subscription id, logs — Step 4 enqueues Celery task here). Step 1's `core/email/router.py` extended: (a) `include_router(microsoft_router)`, (b) `_teardown_provider_watch` dispatch grown a `microsoft` branch calling `unsubscribe_quiet(row, db, subscription_id=row.sync_cursor)` BEFORE token nulling. `config.py` + `.env.example` extended with `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT` (default `common`), `MICROSOFT_GRAPH_REDIRECT_URI`, `MICROSOFT_GRAPH_WEBHOOK_URL` (optional; empty disables push). Tests cover: MicrosoftProvider URL composition + 503 without client + token-exchange round-trip + refresh-token rotation; GraphClient bearer-after-refresh + 429-retry-after-then-success (monkey-patched asyncio.sleep) + 4xx-raises-GraphHTTPError + disconnected-account-409-at-init; sync.backfill filter-walk + nextLink pagination + delta-cursor seeding; sync.sync_incremental delta-walk + 410-marks-delta-expired + no-cursor RuntimeError; send hard-cap blocks (counter unchanged, no Graph call) + happy path increments (b64 encoded body) + Graph-failure rolls counter back; webhook clientState determinism + uniqueness + decode_notification happy + decode-missing-value-400 + assert_client_state-mismatch-401; address-extraction across from/to/cc/bcc + header reconstruction with conversation id. **Notable adaptations:** (a) **Refresh-token rotation handled in TokenSet** — Microsoft returns a new refresh token on every refresh (opposite of Google); the existing Step 1 `service.refresh_if_expired` already re-encrypts when `fresh.refresh_token` is not None, so no Step 1 change needed; (b) **OAuth client is SEPARATE from Google's** — different OAuth provider, different App Registration on Azure portal; reuses Step 1's Fernet token storage + state-signing HMAC; (c) **Subscription id stored in `sync_cursor`** for v1 — same column reused across providers because Step 3 push is HTTPS+public-URL gated (no localhost dev path); when Step 4 lands the renewal scheduler, a dedicated `email_accounts.subscription_id` column will split this; (d) **Subscriptions are OPTIONAL** — when `MICROSOFT_GRAPH_WEBHOOK_URL` is empty, `subscribe_if_configured` no-ops, `/webhook` returns 503; Step 4's poll keeps the mailbox in sync; (e) **clientState is deterministic HMAC** of `account_id` — no extra column needed, rotates with `JWT_SECRET_KEY`, constant-time compare on validation; (f) **No `respx` dependency added** — same `_StubHttp` pattern as Gmail tests. Smoke verified: `GET /microsoft/authorize` returns 503 with detail "Microsoft OAuth client is not configured" when `MICROSOFT_CLIENT_ID` is empty (correct — it tells the rep the provider isn't set up); `POST /microsoft/webhook` returns 503 with topic unset; `GET /microsoft/callback?error=consent_required` redirects 302 → `…?status=microsoft_denied&reason=consent_required`; Step 1 `GET /accounts` still 200 (no regression). **Azure App Registration NOT yet provisioned** — manual step required before browser-testing the OAuth flow; instructions in `.env.example`.
**Depends on:** Step 1 (`email_accounts` table + OAuth scaffolding). External: Azure App Registration with Mail.ReadWrite + Mail.Send + offline_access scopes.

---

## Scope

In-scope:

- `core/email/microsoft/` sub-package:
  - `client.py` — wrapper over `https://graph.microsoft.com/v1.0/me/...`. Handles 429 with `Retry-After`.
  - `sync.py` — `backfill(account, days=30)` and `sync_incremental(account)` using `/me/messages/delta?$select=...`.
  - `send.py` — `send(account, raw_mime: bytes) -> message_id` via `POST /me/sendMail` (or `/me/messages` + `/$value` PUT for raw MIME; pick the PUT path for parity with Gmail).
  - `webhook.py` — change-notification subscription setup + webhook handler at `POST /api/v1/email/microsoft/webhook`.
  - `__init__.py` — registers the `microsoft` provider into the OAuth registry.
- OAuth scopes: `Mail.ReadWrite`, `Mail.Send`, `offline_access`, `User.Read`.
- Connect endpoint: `GET /api/v1/email/microsoft/connect` + `GET /api/v1/email/microsoft/callback`.
- Change notification subscription on connect (`POST /subscriptions` with `changeType=created,updated,deleted`, `resource=/me/messages`, `expirationDateTime=now+3d`). Renew every 2 days via Celery task.

Out of scope:

- Sync daemon (Step 4) — primitives only here.
- Conversations adapter (Step 5).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/email/microsoft/__init__.py` | created — provider registration |
| `api/src/app/core/email/microsoft/client.py` | created |
| `api/src/app/core/email/microsoft/sync.py` | created |
| `api/src/app/core/email/microsoft/send.py` | created |
| `api/src/app/core/email/microsoft/webhook.py` | created |
| `api/src/app/core/email/router.py` | modified — add `/microsoft/connect`, `/microsoft/callback`, `/microsoft/webhook` |
| `.env.example` | modified — add `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT='common'`, `MICROSOFT_WEBHOOK_URL` |
| `api/tests/test_email_microsoft.py` | created |

**8 files.**

## Plan

1. Set up Azure App Registration. Multi-tenant. Add redirect URI `<API>/api/v1/email/microsoft/callback`. Generate client secret. Add API permissions for the listed scopes; grant admin consent on a test tenant.
2. `client.py`: `GraphClient(account)` with `list_messages_delta(delta_link)`, `get_message_raw(id)`, `send_raw(raw)`, `create_subscription(...)`, `renew_subscription(sub_id)`, `delete_subscription(sub_id)`.
3. `sync.py`:
   - `backfill`: `/me/messages?$filter=receivedDateTime ge {30d_ago}&$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime`. Page via `@odata.nextLink`. For each, match recipients against `contacts.email`; matched → fetch raw via `$value` and hand to conversations adapter. On last page, capture `@odata.deltaLink` → store as `sync_cursor`.
   - `sync_incremental`: hit the `deltaLink`. Process events. Update cursor to new `deltaLink`.
4. `send.py`: build raw MIME → POST to `/me/messages/$value` with `Content-Type: text/plain` (Graph accepts RFC 2822). Returns the new message id. Increments `daily_sent_count`.
5. `webhook.py`:
   - On connect: create a subscription with `clientState` = HMAC of the account id (echoed back by Graph in notifications for validation).
   - Webhook handler: validates clientState, enqueues sync task for the matching account.
   - Validation handshake: Graph sends a `validationToken` query param on subscription creation; echo it back as plain text.
6. Router endpoints.

## Tests

`api/tests/test_email_microsoft.py` (uses `respx`):

- **OAuth roundtrip:** state validates; token exchange returns access + refresh; account row created.
- **Delta sync:** mock `/messages` page 1 returning 3 messages + `nextLink`, page 2 returning 2 messages + `deltaLink`. Verify 5 conversations created for matched contacts (seeded), `sync_cursor` = the deltaLink.
- **Incremental from deltaLink:** mock deltaLink response with 1 updated + 1 deleted message. Verify update + tombstone applied.
- **Send:** mock 202 from Graph. Send returns generated id; `daily_sent_count` increments.
- **Webhook validation handshake:** GET with `validationToken=abc` echoes `abc` as `text/plain`.
- **Webhook notification:** POST with valid `clientState` enqueues sync task. Bad clientState → 401.
- **Subscription renewal:** Celery task `renew_microsoft_subscription(account_id)` calls `renew` and updates `expirationDateTime`.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_email_microsoft.py -v

# Browser flow:
# GET /api/v1/email/microsoft/connect → consent in MS → land back on callback
# curl http://localhost:8000/api/v1/email/accounts → 1 row with provider='microsoft'
```

## Risks

- **Publisher verification.** Multi-tenant Graph apps require MPN ID + publisher verification (~2–3 weeks).
- **Subscription expiry.** Graph subscriptions max out at 3 days for mail. Must renew. The renewal Celery task scheduled in Step 4 must always run.
- **Webhook delivery URL must be HTTPS + publicly reachable.** Localhost dev: tunnel via ngrok or similar. Document in setup notes.
- **Quota: 10K requests per 10 minutes per app per tenant.** A large mailbox backfill can blow this. Backoff on 429.
- **`/me/sendMail` vs `/me/messages/$value`:** picking `$value` for raw MIME parity with Gmail. If Graph rejects raw MIME for any combination of tenant policy, fall back to a parsed-payload path. Document the fallback.

## Rollback

Delete files. Revert router + env edits. Existing subscriptions die naturally at expiry (3 days max). Renewal task stops if Step 4 is also rolled back.
