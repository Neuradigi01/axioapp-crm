# Step 5 — user.signed_up event + Welcome trigger seed

**Goal:** Publish `user.signed_up` from the existing registration flow + seed a default "User Welcome" trigger at every new-org creation so signups immediately get a welcome email. This is the first of the two specific manager asks ("welcome mail at the same") landed end-to-end.
**Status:** Pending
**Depends on:** Steps 1-4 (engine live). `tasks/template-library/` Step 10 (Email channel usable end-to-end).

---

## Scope

In-scope:
- `core/events/event_catalog.py` (created in Step 3): add `user.signed_up` entry with shape `{user_id, org_id, email, full_name, signed_up_at}`.
- `core/auth/router.py` (existing registration endpoint): after committing the new user/org rows, call `events.publish("user.signed_up", payload, org_id=...)` with a deterministic event_id of `f"signup:{user_id}"`.
- `core/templates/seeds.py` (new helper) and `core/automation/seeds.py` (new helper):
  - `seed_user_welcome_template(org_id, db) → MessageTemplate` — inserts a default email template named "User Welcome", body uses `{{user.full_name}}` + `{{org.name}}` variables, `internal_status='published'`. Idempotent on (org_id, name).
  - `seed_user_welcome_trigger(org_id, template_id, db) → AutomationTrigger` — inserts a default `user.signed_up → email → template_id` trigger with `delay_seconds=0`, `recipient_resolver=user.email`. Idempotent.
- `core/tenants/service.py` (existing org-creation path): call both seeds during new-org creation, inside the same transaction that creates the org.
- Migration `<ts>_seed_user_welcome_existing_orgs.py`:
  - Backfills the template + trigger for every existing org.
- Tests: signing up a fresh org → both seeded rows exist → publishing `user.signed_up` fires the trigger → the test user's email gets the welcome message.

Out of scope:
- Lead Confirmation seed (Step 6).
- Frontend UI for inspecting the seeded trigger (Steps 7 + 9 — operator can already edit it via the API).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | edit — register `user.signed_up` shape |
| `API/src/app/core/auth/router.py` | edit — publish `user.signed_up` after signup commit |
| `API/src/app/core/templates/seeds.py` | **NEW** |
| `API/src/app/core/automation/seeds.py` | **NEW** |
| `API/src/app/core/tenants/service.py` | edit — call both seeds on org creation |
| `API/alembic/versions/<ts>_seed_user_welcome_existing_orgs.py` | **NEW** — backfill |
| `API/tests/automation/test_user_signed_up.py` | **NEW** |
| `API/tests/templates/test_user_welcome_seed.py` | **NEW** |

**~8 files. ~420 lines.**

## Plan

1. Catalog: register the new event-type with sample shape.
2. Seeds: idempotent inserters for template + trigger.
3. Tenants service: call seeds on org create.
4. Auth router: publish event after signup commit (NOT inside the same transaction — commit must succeed first; the bus is fire-and-forget so this is safe).
5. Backfill migration: loop existing orgs, run both seeders.
6. Tests: full end-to-end — fresh signup arrives in test mailbox.

## DB changes / migrations

One backfill migration. No schema change.

## Tests

7 pytest cases:
- `test_new_org_seeds_user_welcome_template`
- `test_new_org_seeds_user_welcome_trigger`
- `test_seeds_idempotent`
- `test_signup_publishes_user_signed_up_event`
- `test_user_signed_up_event_fires_seeded_trigger`
- `test_welcome_email_renders_user_name_and_org_name`
- `test_disabling_seeded_trigger_skips_send`

## Smoke

```
1. Register a fresh tenant via /api/v1/auth/register.
2. Check audit log: user.signed_up event present.
3. Check tbl_automation_runs: one row with status=sent (or queued → sent after Celery cycle).
4. Inbox of the new Owner has the welcome email.
5. Open /api/v1/automations/triggers as Owner → "User Welcome" trigger visible + enabled.
6. PATCH /triggers/{id} {enabled: false} → re-trigger signup for a second test tenant → run row written with status=skipped (or no row, depending on implementation — service-level check before run).
```

## Risks

- Publishing AFTER commit but inside the request — if the publish call raises, the signup still succeeded. Catch + log; don't bubble.
- Backfill on production orgs: the seed inserts a NEW trigger in every existing org. Document in the migration that operators with custom workflows should NOT run this in production until they've reviewed the seeded copies.

## Self-check (10 rules)

`core/auth/` + `core/tenants/` + `core/templates/` + `core/automation/`. ✓ org_id on every seed row. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already in place. ✓ pack.yaml untouched. ✓ 8 files / ~420 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 5 — user.signed_up event + Welcome trigger seed
Files: 8
Verify: new signup → audit event published → automation run scheduled → welcome email in inbox. Backfill writes template + trigger for every existing org.
Tests: 7 pytest cases.
Awaiting "proceed".
```
