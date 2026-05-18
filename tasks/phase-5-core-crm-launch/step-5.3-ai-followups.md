# Step 5.3 — AI Auto Follow-up Schedule

**Goal:** Day 1 / Day 3 / Day 7 follow-up scheduler reading from AI Settings + pack manifest templates. Celery beat tasks.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** 5.7, 4.2 (manifest follow_up_schedule), 3.15 (campaigns)
**Status:** Pending

## Scope
**In-scope:**
- `app/core/ai/follow_ups.py`: scheduler that creates follow-up jobs for new leads/contacts.
- Celery beat schedule: nightly task `enqueue_due_followups` that finds leads/walk-ins due for Day 1/3/7 follow-ups and enqueues per-row send tasks.
- Templates from pack manifest's `follow_up_schedule` (with placeholders like `{{contact.full_name}}`, `{{store.name}}`).
- Channel-agnostic (defaults to WhatsApp, configurable per-step in manifest).
- Endpoint `POST /ai/follow-ups/{lead_id}/skip` to opt-out.
- Settings: `AI_FOLLOWUP_ENABLED` toggle (org-level via OrgSettings).

## Files to touch
- `api/src/app/core/ai/follow_ups.py` (created)
- `api/src/app/core/ai/tasks.py` (created — Celery)
- `api/src/app/celery/__init__.py` (modified — beat schedule)
- `api/src/app/core/ai/router.py` (modified — skip endpoint)

## Plan
1. Resolve eligible leads: `created_at` was N days ago AND no follow-up of that step yet AND lead status is active.
2. Render template with Jinja-like substitution (only safe fields).
3. Send via channel adapter (default WhatsApp); persist Activity (`type='whatsapp'`) and a record in a small `followup_history` table to prevent duplicate sends.
4. New table `followup_history` (TenantScoped): id, lead_id, step (day_1/day_3/day_7), sent_at, channel, message_id.
5. Migration `0030_followup_history.py`.

## Tests to add
- `tests/test_followup_scheduler.py` — eligible row → enqueued; second run skips already-sent.

## Verification checklist
**Backend:**
- create a fresh lead.
- run `enqueue_due_followups` (manually or wait for beat) at +1 day → message sent.

## Self-check (10 rules)
- [ ] Pack manifest is the source of templates (rule 7).
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 5.9.
