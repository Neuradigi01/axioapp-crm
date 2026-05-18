# Step 5.4 — Reviews automation

**Goal:** Automatic review request after delivery completion. Configurable in Settings → Reviews. Hooked into the order-delivered event.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** 3.13, 3.15, 4.8 (custom orders), 4.11 (billing)
**Status:** Pending

## Scope
**In-scope:**
- Event: when a Custom Order moves to stage `delivered` OR an Invoice transitions to `paid` AND the order is fully delivered, fire a `review_request_due` event.
- Listener (Celery task) `send_review_request(contact_id, source)` — sends a templated message via the campaigns infrastructure (one-off, audience=single contact).
- Settings: `reviews_auto_request_enabled`, `reviews_auto_request_delay_hours` (default 24), `reviews_auto_request_template`.
- Idempotency: `review_request_history` table (TenantScoped) to prevent duplicate sends per (contact, order_id).

## Files to touch
- `api/src/app/core/reviews/automation.py` (created)
- `api/src/app/core/reviews/models.py` (modified — `ReviewRequestHistory`)
- `api/src/app/packs/furniture/modules/custom_orders/service.py` (modified — emit event on delivered)
- `api/src/app/core/billing/service.py` (modified — emit event on paid+delivered)
- `api/alembic/versions/0032_review_request_history.py` (created)

## Plan
1. Define a small in-process event bus (or use Celery directly with task chains) — DEFAULT: Celery task per event, no separate bus.
2. `send_review_request` task respects delay_hours via `apply_async(countdown=...)`.
3. Idempotency check before sending.
4. Records an Activity (`type='whatsapp'`) on the contact.

## Tests to add
- `tests/test_review_automation.py` — delivered → message scheduled; second trigger no-ops.

## Verification checklist
**Backend:**
- mark a custom order delivered → after delay, message sent + Activity logged.
- second delivered (same order) → no second message.

## Self-check (10 rules)
- [ ] Source from settings (review_source default 'google'); template from settings; not hardcoded.
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 5.12.
