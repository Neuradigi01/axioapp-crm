# Step 5 — Backend: Meta Lead Ads webhook receiver + signature verification

**Goal:** Receive Meta's `leadgen` webhook deliveries, handle Meta's verify-token GET handshake, verify the `X-Hub-Signature-256` HMAC on every POST, enqueue lead-fetch as a Celery task (Meta payloads carry only `leadgen_id`; we have to call `GET /{leadgen_id}` to get the actual field values), and DLQ on exhaustion. Reuses subscriptions + DLQ infrastructure from Step 3.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Step 4 (Meta OAuth + Page subscription), Step 3 (subscriptions + DLQ tables, retry/audit patterns).

---

## Scope

In-scope:

- Webhook endpoint at `/api/v1/integrations/meta/webhook` — single fixed URL per environment, not per-org (Meta's model).
  - `GET` handler: Meta's verify-token handshake. If `hub.verify_token == META_WEBHOOK_VERIFY_TOKEN`, echo `hub.challenge`. Else 403.
  - `POST` handler:
    - Verify `X-Hub-Signature-256: sha256=...` HMAC of raw body using `META_APP_SECRET`. Mismatch → 401 + audit.
    - Parse body. Body shape: `{object: "page", entry: [{id: page_id, changes: [{field: "leadgen", value: {leadgen_id, form_id, page_id, ad_id, ...}}]}]}`.
    - For each entry/change, enqueue `process_meta_lead.delay(payload_subset)`.
    - Return 200 immediately.
- Celery task `process_meta_lead`:
  - Look up the integration by `page_id` (find integration row whose token has access to this page — query Meta's `/{page_id}` to confirm via stored Page tokens, OR look up via a cached `(integration_id, page_id)` mapping populated during subscribe).
  - Find the `integration_subscriptions` row by `external_form_id`. None → DLQ.
  - Call Meta Graph API `GET /{leadgen_id}?fields=created_time,id,field_data,ad_id,campaign_id` using a Page token.
  - Apply the subscription's field mapping to convert `field_data: [{name, values:[v]}, ...]` to `LeadCreate`.
  - Find-or-create contact, create lead with `source='meta_ads'`, `attribution={external_form_id, external_lead_id, page_id, ad_id, campaign_id}`.
  - Same retry policy as Google webhook (Step 3): max_retries=5, exponential backoff.
  - Same DLQ on exhaustion.
  - Idempotency: `(provider='meta_ads', external_lead_id)` check; skip if exists.
- Audit events shared with Step 3 (`integration.webhook.received`, `integration.webhook.invalid_signature`, `integration.webhook.dlq`) — just provider-tagged.
- Persist `(integration_id, page_id, page_token_enc)` in a new small table `meta_page_tokens` so the worker can act on Pages without re-fetching `/me/accounts` on every webhook delivery. Populated/updated during `subscribe_page` and `unsubscribe_page` from Step 4.
- Tests for: verify-token handshake, signature verify, fetch + map + create, DLQ on missing subscription, idempotency.

Out of scope:

- Field mapping editor — Step 8.
- Frontend — Step 7.
- Cross-source dedup — Step 6.

## The `meta_page_tokens` mini-table

```sql
CREATE TABLE meta_page_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    page_id         TEXT NOT NULL,
    page_name       TEXT,
    page_token_enc  TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (integration_id, page_id)
);

CREATE INDEX meta_page_tokens_page_idx ON meta_page_tokens (page_id);

ALTER TABLE meta_page_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY meta_page_tokens_tenant ON meta_page_tokens
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

(The webhook receiver runs as a service role that bypasses RLS for the initial Page → integration lookup, then narrows to the org's context for downstream operations. Document in the receiver module.)

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_meta_page_tokens.py` | created |
| `api/src/app/core/integrations/meta/models.py` | created — `MetaPageToken` |
| `api/src/app/core/integrations/meta/webhook.py` | created — receiver |
| `api/src/app/core/integrations/meta/tasks.py` | created — `process_meta_lead` |
| `api/src/app/core/integrations/meta/subscriptions.py` | modified — persist Page tokens on subscribe |
| `api/src/app/core/integrations/meta/router.py` | modified — wire webhook GET + POST |
| `api/tests/test_meta_webhook.py` | created |

**7 files, 1 migration.** Inside rule-8 budget.

## Plan

1. Migration: `meta_page_tokens` + RLS.
2. Extend `subscriptions.subscribe_page`: after successful subscription, upsert the Page token into `meta_page_tokens`.
3. Build `webhook.py`:
   - `GET /webhook`: verify-token handshake.
   - `POST /webhook`:
     - Read raw body bytes (FastAPI: `body = await request.body()`).
     - Compute `expected = "sha256=" + hmac.new(META_APP_SECRET.encode(), body, sha256).hexdigest()`. Compare in constant time to `X-Hub-Signature-256` header.
     - Parse JSON. For each `entry.changes` with `field='leadgen'`, enqueue `process_meta_lead.delay({leadgen_id, form_id, page_id, ad_id, ...})`.
     - Return 200.
4. Build `tasks.py`:
   - Look up `meta_page_tokens` by `page_id` → get `(integration_id, org_id, page_token)`. None → DLQ.
   - Look up `integration_subscriptions` by `(integration_id, external_form_id=form_id)`. None → DLQ.
   - Idempotency check: `select 1 from leads where org_id=... and attribution->>'external_lead_id'=leadgen_id and source='meta_ads'`. Exists → no-op + audit.
   - Call `GET https://graph.facebook.com/v19.0/{leadgen_id}?fields=created_time,id,field_data,ad_id,campaign_id&access_token={page_token}`.
   - Apply mapping → build `LeadCreate`.
   - Create lead + emit audit.
5. Wire endpoints. Add a Celery beat task to refresh Page tokens monthly (Meta long-lived Page tokens don't expire but can be revoked; periodic refresh catches revocations early). Out of scope here; flag as a follow-on.
6. Tests.

## Tests

`api/tests/test_meta_webhook.py`:

- **Verify-token handshake:** GET with matching token returns `hub.challenge`. Wrong token → 403.
- **Signature mismatch:** POST with bad `X-Hub-Signature-256` → 401, no task enqueued, audit `invalid_signature`.
- **Signature valid, happy path:** mock Graph API for `/{leadgen_id}` to return field_data. Mock `meta_page_tokens` + `integration_subscriptions` rows. Run task → lead created with `source='meta_ads'`, attribution populated.
- **No page token mapping → DLQ:** receiver enqueues; task can't find page → DLQ.
- **No subscription → DLQ.**
- **Idempotency:** call task twice with same `leadgen_id` → second call is no-op (no second lead).
- **Multi-entry payload:** body with 3 changes → 3 task enqueues.

## Smoke

```powershell
# Set META_WEBHOOK_VERIFY_TOKEN in .env (any random string)
# In Meta app dashboard → Webhooks → set callback URL to your public URL +
#   /api/v1/integrations/meta/webhook + verify token.
# (For local dev, use ngrok or similar to expose port 8000 publicly.)

# Verify handshake (Meta sends this on save)
# Local sim:
curl "http://localhost:8000/api/v1/integrations/meta/webhook?hub.mode=subscribe&hub.verify_token=$env:META_WEBHOOK_VERIFY_TOKEN&hub.challenge=abc123"
# Expect: 200 with body "abc123"

# Simulate a webhook POST (signature must be valid)
$body = '{"object":"page","entry":[{"id":"page1","changes":[{"field":"leadgen","value":{"leadgen_id":"lead1","form_id":"form1","page_id":"page1","ad_id":"ad1"}}]}]}'
$sig = "sha256=" + (use openssl or python to compute HMAC of $body with META_APP_SECRET)
curl -X POST http://localhost:8000/api/v1/integrations/meta/webhook `
  -H "Content-Type: application/json" `
  -H "X-Hub-Signature-256: $sig" `
  -d $body
# Expect 200, then a lead appears in /user/leads (if subscription + Page token are seeded).
```

## Risks

- **Page token leaks via webhook source-inspection:** webhook payloads do not contain Page tokens (only `leadgen_id`). Tokens stay in our DB.
- **Lead retrieval rate limits:** Meta caps `/{leadgen_id}` calls at ~200/hour/Page token. For a viral ad with 1000 leads/hour, we'd hit the limit. Mitigations: backoff + retry in the task; if sustained, queue depth alerting. Out of scope for v1; flag.
- **Webhook URL changes by environment:** dev/staging/prod each register their own URL in Meta. Document.
- **Single webhook URL for all orgs:** Meta sends every org's leads to the same URL. The `page_id` in the payload + our `meta_page_tokens` lookup routes to the correct integration. If two orgs both connected to the same Page (shouldn't happen but technically possible), we'd dual-deliver — accept the duplicate; cross-source dedup (Step 6) catches it.
- **Idempotency check race:** two simultaneous webhook deliveries for the same `leadgen_id` (Meta's retry hitting twice) could both pass the existence check. Mitigation: a unique partial index on `(org_id, source, attribution->>'external_lead_id') WHERE source IN ('google_ads','meta_ads')` so the second insert fails cleanly, caught and audited. **Add this index in this step's migration.**

## Rollback

Reverse migration. Delete new files. Remove webhook URL from Meta app dashboard manually. Existing webhook deliveries return 404; Meta eventually unsubscribes after enough failures (~7 days).
