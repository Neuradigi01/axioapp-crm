# Step 7 — Backend: `email_sequences` + enrollment engine + reply detection

**Goal:** Multi-step drip campaigns at the lead/contact level. A sequence is an ordered list of (delay, template, condition). Reps enroll leads in bulk; the scheduler fires the right template at the right time per enrollment. Any inbound reply from the enrolled contact auto-pauses that enrollment.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Step 5 (adapter), Step 6 (templates), Celery beat.

---

## Scope

In-scope:

- Two migrations:
  - `0XXX_add_email_sequences.py` — `email_sequences` + `email_sequence_steps`.
  - `0YYY_add_email_sequence_enrollments.py` — `email_sequence_enrollments` + `email_sequence_enrollment_steps`.
- `core/email_sequences/` sub-package: `models`, `schemas`, `service`, `router`, `scheduler`, `module`.
- Enrollment lifecycle: `active → completed | paused_on_reply | paused_manual | cancelled`.
- Scheduler (Celery beat task `tick_email_sequences()` every 60s):
  - For every `active` enrollment whose next step's `scheduled_at <= now`: check reply-detection; if no inbound activity since enrollment, render the template + queue a send via the email adapter; advance to next step. If last step, mark `completed`.
  - Reply-detection: query `activities` for any inbound `kind='email'` with `contact_id = enrollment.contact_id` since `enrollment.enrolled_at`. If found, set enrollment to `paused_on_reply`.
- Endpoints `/api/v1/email/sequences`:
  - `GET /` (list).
  - `POST /` (create — name + ordered steps).
  - `GET /{id}` / `PATCH /{id}` / `DELETE /{id}`.
  - `POST /{id}/enroll` body `{contact_ids: [...], lead_ids: [...]}` — bulk enroll. Returns per-id success/skip.
  - `POST /enrollments/{id}/pause` / `POST /enrollments/{id}/resume`.
  - `GET /enrollments?sequence_id=&contact_id=&state=` — list with filters.

Out of scope:

- Branching sequences (if-replied-then-X-else-Y). v1 = linear only. Branching is v2.
- A/B template testing in a step. v2.
- Sequence UI (Step 11).

## Tables

```sql
CREATE TABLE email_sequences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id),
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  UUID NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE TABLE email_sequence_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    sequence_id     UUID NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    step_order      INT NOT NULL,
    delay_days      INT NOT NULL DEFAULT 0,
    template_id     UUID NOT NULL REFERENCES email_templates(id),
    UNIQUE (sequence_id, step_order)
);

CREATE TABLE email_sequence_enrollments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    sequence_id     UUID NOT NULL REFERENCES email_sequences(id),
    contact_id      UUID NOT NULL REFERENCES contacts(id),
    lead_id         UUID REFERENCES leads(id),
    enrolled_by     UUID NOT NULL REFERENCES users(id),
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    state           TEXT NOT NULL DEFAULT 'active'
                    CHECK (state IN ('active','completed','paused_on_reply','paused_manual','cancelled')),
    state_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    current_step_order INT NOT NULL DEFAULT 1
);

CREATE TABLE email_sequence_enrollment_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    enrollment_id   UUID NOT NULL REFERENCES email_sequence_enrollments(id) ON DELETE CASCADE,
    step_id         UUID NOT NULL REFERENCES email_sequence_steps(id),
    scheduled_at    TIMESTAMPTZ NOT NULL,
    sent_at         TIMESTAMPTZ,
    skipped         BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason     TEXT,
    message_id      UUID REFERENCES messages(id)
);

CREATE INDEX email_sequence_enrollment_steps_due_idx
    ON email_sequence_enrollment_steps (scheduled_at)
    WHERE sent_at IS NULL AND skipped = FALSE;

-- RLS on all four
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_email_sequences.py` | created |
| `api/alembic/versions/0YYY_add_email_sequence_enrollments.py` | created |
| `api/src/app/core/email_sequences/__init__.py` | created |
| `api/src/app/core/email_sequences/models.py` | created |
| `api/src/app/core/email_sequences/schemas.py` | created |
| `api/src/app/core/email_sequences/service.py` | created |
| `api/src/app/core/email_sequences/router.py` | created |
| `api/src/app/core/email_sequences/scheduler.py` | created |
| `api/src/app/core/email_sequences/module.py` | created |
| `api/src/app/core/celery.py` | modified — add `tick_email_sequences` to beat |
| `api/src/app/core/permissions/registry.py` | modified — register `email.sequences.manage`, `email.sequences.enroll` |
| `api/src/app/main.py` | modified — include router |
| `api/tests/test_email_sequences.py` | created |

**13 files, 2 migrations.** This is the largest step in the track because the sequence engine is one logical unit. Splitting model+enrollment into two PRs is worth considering if reviewer load is a concern, but the migrations are tightly coupled so they stay together.

## Plan

1. Two migrations: first lands the static sequence/steps definitions, second lands the per-enrollment runtime state. Both have RLS.
2. `service.create_sequence(name, steps: [(delay_days, template_id), ...])`. Validates all template_ids belong to the org and are active.
3. `service.enroll(sequence_id, contact_ids, lead_ids, actor)`:
   - For each contact, create `email_sequence_enrollments` row + a `email_sequence_enrollment_steps` row for step 1 with `scheduled_at = now()`.
   - Dedupe: if there's an active enrollment for (sequence, contact), skip with `reason='already_enrolled'`.
   - Return per-input results so the UI shows X enrolled / Y skipped.
4. `scheduler.tick()`:
   - Query due `email_sequence_enrollment_steps` (sent_at NULL, scheduled_at <= now, skipped FALSE) — limit 200/tick.
   - For each, in a transaction:
     - Lock the enrollment row.
     - Run reply-detection: any inbound email activity since `enrollment.enrolled_at`?
       - If yes: set enrollment state = `paused_on_reply`. Skip this step with reason.
     - Else: render the template via Step 6 `service.render`. Call adapter `send`. Persist resulting `message_id`. Mark this step sent.
     - If there's a next step: insert next step row with `scheduled_at = now() + delay_days`.
     - Else: set enrollment state = `completed`.
5. `pause` / `resume` endpoints toggle state between `active` and `paused_manual`. Pausing also marks any future scheduled-step rows as cancelled (the scheduler ignores them).

## Tests

`api/tests/test_email_sequences.py`:

- **Create sequence with 3 steps:** persists; cross-org template id → 400.
- **Enroll bulk:** 5 contacts → 5 enrollments + 5 step-1 rows scheduled at now.
- **Dedup on re-enroll:** enroll same contact twice → second call returns skipped.
- **Tick fires step 1, schedules step 2:** monkeypatch adapter.send to no-op; run tick → step 1 marked sent, step 2 row inserted at now+delay.
- **Reply detection pauses:** seed inbound email activity after enrollment; run tick → enrollment state = `paused_on_reply`, no send happens.
- **Completion:** advance time past all 3 steps; tick three times → enrollment state = `completed`.
- **Manual pause cancels future steps:** pause enrollment after step 1; advance time; tick → step 2 not sent (skipped with reason).
- **Resume reschedules:** resume → next due step inserted at now+delay.
- **Tick respects org RLS:** two orgs' enrollments processed independently; org context set per-row.
- **Tick limit:** seed 300 due rows → only 200 processed in one tick; next tick processes the rest.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_email_sequences.py -v

# Create + enroll:
$token = "<owner JWT>"
curl -X POST http://localhost:8000/api/v1/email/sequences `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"name":"Designer outreach","steps":[{"delay_days":0,"template_id":"$t1"},{"delay_days":2,"template_id":"$t2"},{"delay_days":5,"template_id":"$t3"}]}'

curl -X POST http://localhost:8000/api/v1/email/sequences/$sid/enroll `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"contact_ids":["$c1","$c2"]}'
```

## Risks

- **Scheduler clock skew across workers.** Multiple celery workers ticking simultaneously would double-send. Mitigation: `FOR UPDATE SKIP LOCKED` on the due-step query inside the transaction. Verified by test 9.
- **Per-account daily cap interaction.** A 100-lead enrollment all fires step 1 at t=0 → if sender's account is at 100 already, hits the cap. Mitigation: catch `HardCapExceeded` from adapter, reschedule the step to tomorrow at the same time. Document in the scheduler code.
- **Tick latency.** A 60-second beat tick means step delays are within ±60s. Acceptable for marketing/sales sequences. Document in operational notes.
- **Enrollment storm on first deploy.** If a customer enrolls 10K leads at once, tick floods. Mitigation: limit 200/tick (test 10) — at worst 12K/hour throughput, well within Gmail/Graph rate limits.

## Rollback

`alembic downgrade -2` (back through both migrations). Delete files. Revert celery + permissions + main.py edits. In-flight enrollments are lost — document in ops notes that rollback after enrollments exist is destructive.
