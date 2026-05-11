# Step 3.8 — Conversations: backend (architecture)

**Goal:** Channel-agnostic Conversations engine. `conversations` and `messages` tables. `channels` registry — each channel adapter implements `send`, `receive_webhook`. WhatsApp adapter is built next; this step lays the abstraction.
**Phase:** 3
**Depends on:** 2.4, 1.8
**Status:** Pending

## Scope
**In-scope:**
- Models:
  - `Conversation` (TenantScoped): id, org_id, channel (enum: whatsapp/instagram/facebook/web/sms/email), external_id (e.g., WhatsApp phone), contact_id (FK→contacts, nullable), assigned_to_id, status (open/snoozed/closed), ai_handling (bool), last_message_at, unread_count, created_at.
  - `Message` (TenantScoped): id, org_id, conversation_id, direction (in/out), sender_user_id (nullable), text, attachments JSONB, channel_message_id, payload JSONB, sent_at, delivered_at, read_at, created_at.
- Migration + RLS + indexes (`org_id, last_message_at desc`, `external_id`).
- Channel adapter interface (Python protocol class) `ChannelAdapter` with methods:
  - `send(conversation, text, attachments) -> ChannelMessageRef`
  - `parse_webhook(payload) -> InboundMessage`
- Channel registry: `register(channel_id, adapter_factory)`; resolved at runtime.
- Endpoints:
  - `GET /api/v1/conversations` (filters: channel, status, assigned_to, q)
  - `GET /api/v1/conversations/{id}` + messages
  - `POST /api/v1/conversations/{id}/messages` — sends via channel adapter.
  - `PATCH /api/v1/conversations/{id}` — assign, status, ai_handling toggle.
  - `POST /api/v1/conversations/webhooks/{channel}` — generic webhook intake; dispatches to adapter.
- Permission: `conversations.read`, `conversations.write`.

**Out of scope:**
- WhatsApp adapter — 3.9.
- Frontend — 3.10.
- AI handling — 5.7.

## Files to touch
- `api/src/app/core/conversations/{__init__,models,schemas,service,router,adapters,registry,module}.py` (created)
- `api/alembic/versions/0018_conversations.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Models + migration.
2. Adapter protocol + registry. Adapters live under `core/conversations/adapters/<channel>.py`.
3. Service: `send_outbound(conversation_id, user_id, text)` resolves adapter, calls `send`, persists message.
4. Webhook intake: validates channel, calls `adapter.parse_webhook`, persists inbound message, broadcasts notification (uses 2.15 service).
5. Activity log on first message in a conversation tied to a contact.

## Tests to add
- `tests/test_conversations_crud.py`
- `tests/test_channel_registry.py` — register a fake adapter, send routes correctly.

## Verification checklist
**Backend:**
- `GET /conversations` → empty.
- with a fake adapter registered (test only), `POST /conversations/{id}/messages` calls the adapter.

## Self-check (10 rules)
- [ ] Engine is channel-agnostic.
- [ ] org_id + RLS.
- [ ] Adapter registry mirrors module registry pattern (rule 5/6).

## Stop & report
Await "proceed" before Step 3.9.
