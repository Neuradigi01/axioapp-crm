# Step 3.15 — Marketing / Campaigns: backend

**Goal:** `campaigns`, `campaign_messages`, `campaign_stats`. Channel-agnostic engine (uses the same channel adapters as Conversations). Schedule via Celery.
**Phase:** 3
**Depends on:** 3.8 (channel registry), 1.2 (Celery)
**Status:** Pending

## Scope
**In-scope:**
- Models:
  - `Campaign` (TenantScoped): id, org_id, name, channel, audience_filter JSONB (stored query against contacts), template (text or template_id), schedule_at, status (draft/scheduled/running/done/failed), created_by_id, created_at.
  - `CampaignMessage` (TenantScoped): id, org_id, campaign_id, contact_id, channel_message_id, status (queued/sent/delivered/read/failed), sent_at.
  - `CampaignStats` (TenantScoped, view or denormalized): campaign_id, sent, delivered, read, replied, opt_out.
- Migration + RLS + indexes.
- Service: `enqueue(campaign_id)` — resolves audience, splits into chunks, enqueues Celery tasks per chunk.
- Celery task `send_campaign_chunk(campaign_id, contact_ids[])` — uses channel adapter from registry.
- Endpoints: `/campaigns` CRUD, `POST /campaigns/{id}/start`, `GET /campaigns/{id}/stats`.
- Permission: `campaigns.read`, `campaigns.write`, `campaigns.send`.

## Files to touch
- `api/src/app/core/campaigns/{__init__,models,schemas,service,router,tasks,module}.py` (created)
- `api/alembic/versions/0021_campaigns.py` (created)
- `api/src/app/celery/__init__.py` (modified — register tasks module)
- `api/src/app/main.py` (modified)

## Plan
1. Models + migration. `audience_filter` is the same JSONB filter shape as `/contacts` query (so re-uses same query builder).
2. `start` endpoint: validates schedule_at >= now, transitions to `scheduled`; if immediate, enqueues now.
3. Celery task: chunks of 50 contacts; per contact opens a conversation (or reuses existing), sends via adapter, persists CampaignMessage.
4. Stats: aggregate query.

## Tests to add
- `tests/test_campaigns_audience.py` — audience_filter resolves correctly.
- `tests/test_campaigns_send_dryrun.py` — fake adapter; chunks processed.

## Verification checklist
**Backend:**
- create campaign with audience_filter → start → Celery worker processes → CampaignMessages persisted.
- `GET /campaigns/{id}/stats` → counts.

## Self-check (10 rules)
- [ ] Channel-agnostic; reuses 3.8 registry.
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 3.16.
