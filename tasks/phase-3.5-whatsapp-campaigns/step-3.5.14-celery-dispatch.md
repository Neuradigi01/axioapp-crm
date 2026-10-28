# Step 3.5.14 — Celery dispatch: async worker + scheduled campaigns + beat

**Goal:** Move campaign dispatch from in-process (CELERY_ENABLED=false dev fallback) to a real Celery worker so 10,000-contact campaigns don't block the API request, and so scheduled campaigns fire at their `schedule_at` time via celery-beat.

**Phase:** 3.5
**Depends on:** 1.2 (Celery infrastructure), 3.5.6 (dispatch_chunk text/template branch)
**Status:** ✅ COMPLETED — 112/112 tests; eager-mode dev + Celery prod path wired

After this step:
- Operator hits "Start campaign" → API returns 200 instantly with `{enqueued: 2,348, chunks: 47}` → Celery worker burns through chunks at the configured rate
- Scheduled campaign (`schedule_at=2026-05-30 10:00`) → celery-beat scans every minute → enqueues at the right time
- Operator can monitor progress live on Step-3.5.13 detail page

---

## Scope

### In-scope

- New `core/campaigns/tasks.py` — Celery task `send_campaign_chunk(campaign_id, contact_ids)` wraps the existing `dispatch_chunk` service function.
- Update `enqueue(campaign_id)`:
  - In dev (`CELERY_ENABLED=false`): runs in-process (existing behavior).
  - In prod (`CELERY_ENABLED=true`): `send_campaign_chunk.delay(campaign_id, chunk)` per chunk.
- Beat schedule: every 60s task `dispatch_scheduled_campaigns()` — finds campaigns where `status='scheduled' AND schedule_at <= now()`, transitions to `running`, calls `enqueue`.
- Per-chunk failure isolation — Celery task retries 3x with exponential backoff on `WhatsAppSendError` (transient Meta 5xx); permanent failures (Meta 4xx) don't retry.
- Status transitions:
  - `draft → scheduled` (on start with future schedule)
  - `scheduled → running` (when beat picks up)
  - `running → done` (when last chunk completes)
  - `running → failed` (when adapter-not-connected blocks at start)
- Existing tests' "in-process" path stays green; new tests cover scheduled + Celery-mode.

### Out-of-scope

- Rate limit (Meta 80msg/sec free tier) → Step 3.5.15.
- DLQ for dead campaigns → existing `integration_dlq` covers webhook-side; campaigns have their own `error` column in CampaignMessage. Separate DLQ deferred.

---

## Files to touch

### Created (1)
- `API/src/app/core/campaigns/tasks.py` — Celery tasks

### Modified (~4)
- `API/src/app/core/campaigns/service.py` — `enqueue` Celery-aware
- `API/src/app/celery/__init__.py` — register the new tasks module + beat schedule
- `API/src/app/core/campaigns/models.py` — N/A (status enum already supports `running`/`scheduled`)
- `API/tests/test_campaigns_celery.py` (new) — task-mode tests

**File budget:** ~5 files.

---

## Plan

1. Celery task signature mirrors existing service function — one-line wrapper.
2. Beat schedule lives in the existing celery config — pattern from other modules (notifications, calls).
3. Retry policy: `autoretry_for=(WhatsAppSendError,)`, `retry_backoff=True`, `max_retries=3`.

---

## Pre-implementation question

**Q:** Scheduled campaigns ke beat schedule par "every minute" check rakhein ya **on-demand wake-up** (when operator schedules, also push the wake-up time)?

- **(a) Every-minute poll.** Simple, no event coordination. Worst-case 60s drift on schedule_at.
- **(b) Per-campaign delayed task** via `apply_async(eta=schedule_at)`. Exact firing time, but every schedule change must re-issue the delayed task.

**Recommendation: (a)** — 60s drift is acceptable for marketing campaigns (operator setting "10:00 AM" doesn't expect 10:00:00.000). Beat polling is simpler ops.

---

## Verification + Self-check + Stop & report — standard
