# Step 3.9 — Conversations: WhatsApp adapter

**Goal:** WhatsApp Business Cloud API adapter (send + webhook). Stub credentials in config. Verify message round-trip.
**Phase:** 3
**Depends on:** 3.8
**Status:** Pending

## Scope
**In-scope:**
- `core/conversations/adapters/whatsapp.py` implementing `ChannelAdapter`:
  - `send(conversation, text, attachments)` → POSTs to WhatsApp Cloud API messages endpoint.
  - `parse_webhook(payload)` → extracts inbound text/media + `external_id`.
  - Webhook signature verification via `X-Hub-Signature-256`.
- New settings: `WHATSAPP_PHONE_ID`, `WHATSAPP_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`.
- Webhook GET (verification) and POST (message intake) handlers wired into `/conversations/webhooks/whatsapp`.
- Contact resolution: lookup contact by phone (with country code normalization); auto-create if not found.

**Out of scope:**
- Instagram/Facebook adapters — later (deferred or added in 5.x if needed).
- Template messages — defer.

## Files to touch
- `api/app/core/conversations/adapters/whatsapp.py` (created)
- `api/app/core/conversations/router.py` (modified — webhook GET + POST)
- `api/app/shared/config.py` (modified — new settings)

## Plan
1. Implement send via httpx async POST.
2. Implement parse_webhook + signature verification (HMAC-SHA256 of body with app secret).
3. Webhook GET (verification): returns `hub.challenge` if `verify_token` matches.
4. Auto-resolve contact by phone; if missing, create with `full_name = phone` placeholder.
5. Persist message + broadcast notification.

## Tests to add
- `tests/test_whatsapp_signature.py`
- `tests/test_whatsapp_send.py` — mocks httpx, asserts request shape.
- `tests/test_whatsapp_webhook.py` — sample inbound payload, asserts message + conversation persisted.

## Verification checklist
**Backend:**
- run pytest → green.
- manual: with stubbed creds and ngrok forwarding, send a real WhatsApp message → arrives in DB. (Optional, dev-environment.)

## Self-check (10 rules)
- [ ] Adapter is the only place that knows WhatsApp API.
- [ ] Signature verified on every webhook.

## Stop & report
Await "proceed" before Step 3.10.
