# Step 2 — Backend: Gmail adapter (OAuth + history-based sync + send)

**Goal:** Implement the Gmail provider: OAuth connect/refresh, initial 30-day backfill, incremental history-based sync, and outbound send via the user's own Gmail account. Plugs into the shared scaffolding from Step 1.
**Track:** App Updates → Email
**Status:** Pending
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
