# Step 3 — Backend: Google Ads webhook receiver + signature verification + retry queue

**Goal:** Receive Google Ads Lead Form webhook deliveries, verify them via the per-org delivery key (Google's "webhookSecret" model), enqueue lead-creation as a Celery task, and surface a DLQ for payloads that exhaust retries.
**Track:** Ad Integrations
**Status:** Pending
**Depends on:** Step 2 (Google OAuth + integration row), Step 1 (integrations table), Manual Lead Entry Step 1 (`lead.source='google_ads'`), Embeddable Widget Step 2 (`leads.attribution` column reused).

---

## Scope

In-scope:

- New migration: add `webhook_secret` (random 32-byte secret per integration row, generated on first connection) + `integration_subscriptions` table (maps `(org_id, provider, external_form_id)` → field mapping). Plus `integration_dlq` table for failed deliveries.
- Webhook endpoint `POST /api/v1/integrations/google/webhook/v1/{webhook_key}`:
  - `webhook_key` = `integration.webhook_secret`. Look up the integration row by it. Unknown key → 401 + audit.
  - Verify the payload by checking `google_key` field in the JSON body matches the stored secret (Google's model: secret embedded in payload body, not header).
  - Enqueue a Celery task `process_google_lead(integration_id, payload)` and return 200 immediately.
- Celery task `process_google_lead`:
  - Look up the `integration_subscriptions` row by `external_form_id` (from payload).
  - If no subscription → DLQ with reason `no_subscription`.
  - Apply the field mapping to convert Google's payload `[{column_name, string_value}, ...]` to a `LeadCreate`.
  - Find-or-create contact by phone/email (Steps 6's dedup; this step uses the bulk-import `dedup.py`).
  - Create lead with `source='google_ads'`, `actor_user_id=None`, `attribution={external_form_id, external_lead_id, campaign_id, gclid}`.
  - Emit audit `integration.webhook.received`.
  - On exception: retry policy `max_retries=5`, exponential backoff (5s, 25s, 2m, 10m, 50m). After exhausting → DLQ.
- `core/integrations/google/dlq.py` — `record_dlq(integration_id, payload, error, retries)`; `list_dlq(org_id)`; `replay_dlq(dlq_id)` (re-enqueues the task).
- Admin endpoints `GET /api/v1/integrations/dlq` and `POST /api/v1/integrations/dlq/{id}/replay`.
- Tests covering: signature match/mismatch, mapping application, dedup, DLQ on exhaustion, replay.

Out of scope:

- Meta webhook — Step 5 (same shape, different provider).
- Cross-source dedup with existing leads from other sources — Step 6.
- Lead routing — Step 6.
- Frontend (subscriptions picker, DLQ UI) — Steps 7/8.

## The new tables

```sql
ALTER TABLE integrations ADD COLUMN webhook_secret TEXT;  -- random per integration; rotated on disconnect
CREATE INDEX integrations_webhook_secret_idx ON integrations (webhook_secret) WHERE webhook_secret IS NOT NULL;

CREATE TABLE integration_subscriptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id),
    integration_id      UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    external_form_id    TEXT NOT NULL,    -- Google Lead Form id, OR Meta form id (Step 5 reuses)
    external_form_label TEXT,
    field_mapping       JSONB NOT NULL DEFAULT '{}',  -- {ad_field: crm_field_key}
    enabled             BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (integration_id, external_form_id)
);
ALTER TABLE integration_subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY integration_subscriptions_tenant ON integration_subscriptions
    USING (org_id = current_setting('app.org_id', true)::uuid);

CREATE TABLE integration_dlq (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    integration_id  UUID REFERENCES integrations(id),  -- nullable if integration deleted
    provider        integration_provider_enum NOT NULL,
    payload         JSONB NOT NULL,
    error_message   TEXT NOT NULL,
    retries_attempted INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at     TIMESTAMPTZ,
    replayed_by     UUID REFERENCES users(id)
);
ALTER TABLE integration_dlq ENABLE ROW LEVEL SECURITY;
CREATE POLICY integration_dlq_tenant ON integration_dlq
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_webhook_secret_and_subscriptions_and_dlq.py` | created |
| `api/src/app/core/integrations/models.py` | modified — add `IntegrationSubscription`, `IntegrationDLQ`; extend `Integration` with `webhook_secret` |
| `api/src/app/core/integrations/schemas.py` | modified — schemas for subscription + DLQ |
| `api/src/app/core/integrations/service.py` | modified — `rotate_webhook_secret(integration)`; subscription CRUD; dlq list/replay |
| `api/src/app/core/integrations/google/webhook.py` | created — receiver |
| `api/src/app/core/integrations/google/tasks.py` | created — `process_google_lead` Celery task |
| `api/src/app/core/integrations/google/dlq.py` | created — DLQ helpers |
| `api/src/app/core/integrations/router.py` | modified — wire webhook + dlq endpoints |
| `api/src/app/core/audit/events.py` | modified — declare webhook events |
| `api/tests/test_google_webhook.py` | created |

**10 files, 1 migration.** At rule-8 ceiling.

## Plan

1. Migration: extend `integrations`, create `integration_subscriptions` + `integration_dlq`. On `service.upsert` for a new integration, generate a random `webhook_secret` via `secrets.token_urlsafe(32)`.
2. Build `webhook.py`:
   - `POST /webhook/v1/{webhook_key}`:
     - Look up integration row by `webhook_secret = webhook_key`. None → 401.
     - Parse JSON body. Verify body's `google_key` field matches `webhook_key` (Google's documented check). Mismatch → 401 + audit `integration.webhook.invalid_signature`.
     - Enqueue `process_google_lead.delay(integration.id, payload)`.
     - Return `{"status": "accepted"}` 200.
   - **Return 200 even if enqueue fails internally** — Google retries on non-2xx and we'd rather log + monitor than have them retry every 401. Exception: 401 on unknown key (intentional).
3. Build `tasks.py`:
   - `@app.task(bind=True, autoretry_for=(Exception,), max_retries=5, retry_backoff=True, retry_backoff_max=3000)`
   - Body:
     - Look up integration. If disconnected → DLQ + abort.
     - Extract `external_form_id` from payload (Google sends `lead_id`, `campaign_id`, `form_id`, and `user_column_data: [{column_name, string_value}, ...]`).
     - Find `integration_subscriptions` row. If none → DLQ.
     - Apply field mapping to build a `LeadCreate` dict.
     - Find-or-create contact, create lead with `source='google_ads'`, `attribution={external_form_id, external_lead_id, campaign_id, gclid}`.
     - Emit `integration.webhook.received` audit event with key id, form id, lead id.
   - On `self.max_retries == self.request.retries`, on the next failure handler → write to DLQ with the latest error.
4. DLQ helpers: simple CRUD. Replay calls `.delay()` again with the original payload.
5. Wire admin endpoints `GET /integrations/dlq` (list, paginated) and `POST /integrations/dlq/{id}/replay`.
6. Tests with the test client + Celery in eager mode (`task_always_eager=True` test setting).

## Tests

`api/tests/test_google_webhook.py`:

- **Unknown key → 401:** POST `/webhook/v1/garbage` → 401, no enqueue.
- **Bad google_key in body → 401:** valid path key but mismatched body key → 401 + audit.
- **Happy path:** integration exists, subscription exists, mapping applies → lead created with `source='google_ads'`, attribution populated.
- **No subscription → DLQ:** integration exists, no subscription row for the form → task DLQs the payload, no lead created.
- **Mapping covers all fields:** subscription mapping `{"FULL_NAME":"contact.full_name","PHONE_NUMBER":"contact.phone","WORK_EMAIL":"contact.email"}` correctly populates the lead.
- **Disconnected integration → DLQ:** disconnect after subscription; webhook → DLQ.
- **Retry exhaustion → DLQ:** inject a transient failure in lead creation, run task; after 5 retries, payload is in DLQ.
- **Replay re-enqueues:** put a row in DLQ, POST replay → task runs, lead created, DLQ row's `replayed_at` set.
- **RLS:** Org A's DLQ rows invisible to Org B.

## Smoke

```powershell
# After Step 2 smoke (integration row exists), copy the webhook_secret from the DB
docker exec template_api-db-1 psql -U postgres -c "select webhook_secret from integrations where provider='google_ads' limit 1;"
$secret = "<from above>"

# Manually POST a sample Google payload (the shape from Google's docs)
curl -X POST "http://localhost:8000/api/v1/integrations/google/webhook/v1/$secret" `
  -H "Content-Type: application/json" `
  -d "{`"google_key`":`"$secret`",`"lead_id`":`"lead-1`",`"campaign_id`":`"camp-1`",`"form_id`":`"form-1`",`"user_column_data`":[{`"column_name`":`"FULL_NAME`",`"string_value`":`"Asha`"},{`"column_name`":`"PHONE_NUMBER`",`"string_value`":`"+919876543210`"}]}"
# Expect 200 (after creating a subscription row for form_id="form-1" — do that first via SQL or future Step 7 UI)

# Confirm lead
curl http://localhost:8000/api/v1/leads -H "Authorization: Bearer $token"
# Expect: the new lead with source="google_ads"
```

## Risks

- **Google retries:** Google retries non-2xx with backoff; 401 from us tells them to give up. Make sure the only 401 we return is for a truly invalid key — transient errors must be 200 (and processed/retried internally).
- **`webhook_secret` rotation:** disconnect → reconnect rotates the secret. Old URL stops working immediately. Document this in Settings UI (Step 7).
- **Celery autoretry on `Exception`:** broad catch. Some exceptions (validation, "subscription missing") should DLQ immediately, not retry. Use `autoretry_for=(httpx.HTTPError, redis.ConnectionError)` instead and explicit `retry()` calls for the others. Confirm exception taxonomy at implementation.
- **DLQ unbounded growth:** add a Celery beat task (later) to purge DLQ older than 90 days. Out of scope here.
- **Replay duplicates:** if a replayed payload was actually partially processed before failing (lead created but task crashed before commit), replay could create duplicate. Idempotency key: `(provider, external_lead_id)` should be unique. Add an index in this migration; lead creation in the task checks this before creating. **Decision: add `attribution.external_lead_id` uniqueness check** in the task; skip if exists.

## Rollback

Reverse migration (drops `webhook_secret`, `integration_subscriptions`, `integration_dlq`). Delete new files. Webhook stops responding; ad platforms stop being able to deliver. Reconnect required after rollback.
