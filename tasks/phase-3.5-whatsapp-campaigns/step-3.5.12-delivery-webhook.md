# Step 3.5.12 — Delivery webhook: per-org routing + delivered_at / read_at tracking

**Goal:** Migrate the WhatsApp inbound webhook from env-var single-tenant to per-org `phone_id` lookup, AND start consuming Meta's `statuses[]` array to mark `CampaignMessage.delivered_at` / `read_at`. Closes the multi-tenant loop opened by Step 3.5.3.

**Phase:** 3.5
**Depends on:** 3.5.1 (`whatsapp_account_configs.phone_id` lookup), 3.5.3 (outbound per-org), existing webhook receiver
**Status:** ✅ COMPLETED — 107/107 tests; env-var WA path fully dropped

After this step Meta sends "delivered" / "read" status updates to the webhook → backend identifies the org by `phone_number_id` in payload → updates the matching `CampaignMessage` row's timestamps. The Settings UI's WhatsApp card shows real per-org webhook URL (different secret per org). Env-var fallback removed.

---

## Scope

### In-scope

- New service helper `find_org_by_phone_id(session, phone_id) -> Integration | None` — DB lookup bypassing tenant filter (similar to `get_by_webhook_secret` in Step-1 integrations service).
- Webhook receiver refactor (`POST /webhooks/whatsapp`):
  - Extract `entry[0].changes[0].value.metadata.phone_number_id` from payload.
  - Look up org → set tenant context → verify signature with org's `app_secret` → process.
  - On unknown phone_id → 404 (log to integration_dlq with reason `unknown_phone_id`).
- New status processing in `parse_webhook` / a sibling:
  - If payload has `statuses[]` (not `messages[]`), update `CampaignMessage` by `channel_message_id`:
    - `status: "delivered"` → `delivered_at = now()`, status field stays `sent` (success) or flips to `delivered` (new value? see DB note)
    - `status: "read"` → `read_at = now()`, status field `read`
    - `status: "failed"` → status `failed`, `error` = payload error message
- Migration `0066_campaign_messages_delivery_timestamps.py` — add `delivered_at`, `read_at` columns + extend enum if status moves through `delivered` / `read` values. Decision in pre-impl Q.
- Drop `register_default_whatsapp_adapter` and the env-var fallback path entirely — all flows now per-org.
- Remove the env-var WhatsApp keys from `config.py` and `.env.example` (cleanup; the old keys are no longer read).

### Out-of-scope

- Real-time UI ticks (UI rendering of new timestamps) → Step 3.5.13.
- Aggregated stats endpoint extension → minor, covered in same step's CampaignStats.

---

## Files to touch

### Created (1)
- `API/alembic/versions/0066_campaign_messages_delivery_timestamps.py`

### Modified (~6)
- `API/src/app/core/integrations/whatsapp/connect.py` — add `find_org_by_phone_id`
- `API/src/app/core/conversations/router.py` — webhook handler rewrite
- `API/src/app/core/conversations/adapters/whatsapp.py` — drop `register_default_whatsapp_adapter`, narrow `parse_webhook` to messages only, add `parse_statuses` helper
- `API/src/app/main.py` — drop `register_default_whatsapp_adapter` lifespan call
- `API/config.py` — drop WHATSAPP_* env keys
- `API/.env.example` — drop WHATSAPP_* entries

**File budget:** ~7 files.

---

## Plan

1. Migration: add timestamp columns; consider extending `campaign_message_status` enum with `delivered` / `read` values (additive — safe).
2. Webhook routing: bypass-tenant lookup → set context → all subsequent ORM queries enforce org via existing filter.
3. Signature verification per org with the org's `app_secret_enc` decrypted on the spot.
4. Drop env-var path — all callers now use DB.
5. Tests cover: status updates, unknown phone_id, signature mismatch per org.

---

## Pre-implementation question

**Q:** `CampaignMessageStatus` enum mein `delivered` / `read` values **add karein** ya sirf timestamp columns par rely karen?

- **(a) Add enum values.** Single source of truth — `status='read'` means read. Migration adds enum values (additive, safe).
- **(b) Timestamps only.** `status` stays `sent`, but `read_at IS NOT NULL` = read. Simpler migration but more complex queries.

**Recommendation: (a)** — analytics queries (`COUNT WHERE status='read'`) become trivial. Enum values are cheap and clarify state.

---

## Verification + Self-check + Stop & report — standard
