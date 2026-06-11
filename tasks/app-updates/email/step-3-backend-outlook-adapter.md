# Step 3 — Backend: Microsoft Graph adapter (OAuth + delta sync + send)

**Goal:** Microsoft 365 / Outlook provider. Same surface as Gmail (OAuth, backfill, incremental, send) but using Microsoft Graph + delta tokens + change notifications instead of Gmail history + Pub/Sub.
**Track:** App Updates → Email
**Status:** Pending
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
