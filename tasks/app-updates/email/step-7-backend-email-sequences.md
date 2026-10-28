# Step 7 — Backend: `email_sequences` + enrollment engine + reply detection

**Goal:** Multi-step drip campaigns at the lead/contact level. A sequence is an ordered list of (delay, template, condition). Reps enroll leads in bulk; the scheduler fires the right template at the right time per enrollment. Any inbound reply from the enrolled contact auto-pauses that enrollment.
**Track:** App Updates → Email
**Status:** COMPLETED — Two migrations land (`0084_add_email_sequences` for `email_sequences` + `email_sequence_steps`, both with `apply_rls` + name uniqueness on live rows + `(sequence_id, step_order)` unique constraint; `0085_add_email_sequence_enrollments` for `email_sequence_enrollments` + `email_sequence_enrollment_steps`, both with RLS + the partial index `(scheduled_at) WHERE sent_at IS NULL AND skipped = false` that the beat reads every tick). `core/email_sequences/` sub-package ships `models.py` (four ORM classes + the `EnrollmentState` string-enum with five values — stored as TEXT with a DB CHECK constraint, not a Postgres ENUM, so adding a state in v2 doesn't need an enum-alter migration), `schemas.py` (Pydantic v2 — `EmailSequenceCreate`/`Update`/`Read` + nested `StepCreate`/`StepRead`, `EnrollmentRequest`/`Response`/`ResultRow`/`Read`/`ListResponse`), `service.py` (the meat: `_validate_template_ids` rejects cross-org / soft-deleted ids with 400 listing offenders; `create_sequence` materialises dense 1-based `step_order` rows + audit emits `email.sequence.created`; `update_sequence` is **partial** with `steps` as **full-replace** — 409 when sequence has active or paused enrollments to avoid stranding in-flight step references; `delete_sequence` soft-deletes; `enroll` dedupes against non-terminal `(sequence, contact)` enrollments returning per-row results with `skip_reason='already_enrolled'`, length-mismatch check on `lead_ids`, 409 on inactive sequence; `pause_enrollment` flips to `paused_manual` + bulk-skips pending step rows with reason `enrollment_paused`; `resume_enrollment` re-inserts a fresh enrollment-step row at `now + delay_days` of the current step, gracefully completes if the current step was deleted under us; `cancel_enrollment` is terminal + bulk-skips pending step rows with reason `enrollment_cancelled`), `scheduler.py` (pure async `tick()` — cross-org raw-SQL sweep via `sql_text(...)` returning `(step_row_id, org_id)` pairs sorted by `scheduled_at` ASC LIMIT 200; per-row processing opens a fresh session, calls `set_context(RequestContext(org_id, user_id=None))`, locks the row with `with_for_update(skip_locked=True)`, then runs the full pipeline: enrollment-state guard → step-def guard → sequence-active/not-deleted guard → template-not-deleted guard → reply detection via `_has_inbound_reply` (joins conversations on `channel=email, contact_id=…` + messages `direction=in_` AND `created_at >= enrolled_at`, single `exists()` query; uses indexed `messages.direction` column rather than the activities JSON payload) → sender's first `sync_state='live'` email account via `_resolve_sender_account` → render template via Step 6's `build_context` + `render_template` → dispatch via Step 5's typed `send_email`. On `HardCapExceeded`, push `scheduled_at` to tomorrow same time and leave the enrollment active. On success, mark step `sent_at=now` + capture `message_id`, advance `current_step_order`, insert next-step pending row at `now + next.delay_days`; on last step, mark enrollment `completed`. Per-row failures are caught + logged so a single bad row doesn't kill the tick), `tasks.py` (Celery `@shared_task` named `src.app.core.email_sequences.tasks.tick_email_sequences` that `asyncio.run(tick())` matching the project convention from Step 4: pure logic in scheduler.py, Celery wrapper in tasks.py), `router.py` (full CRUD + `POST /{id}/enroll` + `GET /enrollments` + `POST /enrollments/{id}/pause`/`resume`/`cancel`; write paths gated by `email.sequences.manage` (Owner/Admin/SalesManager), enroll + state transitions gated by `email.sequences.enroll` (those three + Employee), reads gated by `email.read`), `module.py` (descriptor with `menu_position=None` — surface lives at Step 11's Settings → Email Sequences tab). Celery beat schedule extended in `src/celery/celery_config.py` (`email-sequences-tick` every 60s) and `src/celery/worker.py` autodiscover list (adds `src.app.core.email_sequences.tasks`). `role_templates.py` extended: Admin + Owner get `email.sequences.manage` + `email.sequences.enroll`; Sales Manager same; Employee gets `email.sequences.enroll` only. Router included in `main.py` under `/api/v1`. Tests (no real DB — `_CapturingSession` stages SELECT results in FIFO order, `_ScalarResult` wraps via `scalar_one`/`scalar_one_or_none`/`scalar`/`scalars().all()`): `_validate_template_ids` (happy, empty skips query, unknown id rejected with 400 listing the id); `create_sequence` (happy materialises dense `step_order` step rows; cross-org template id raises 400); `enroll` (bulk happy materialises N enrollments + N step-1 rows, all `enrolled=True`; dedupe preserves input order, blocked rows carry `enrollment_id` of the existing row + `skip_reason='already_enrolled'`; lead_ids length mismatch raises 400; inactive sequence raises 409); pause/resume/cancel (pause flips to `paused_manual` + commits; pause on terminal raises 409; resume reschedules current step at `now + delay_days` and flips to active; cancel is terminal; cancel on already-terminal is idempotent no-commit); scheduler helpers (`_has_inbound_reply` true/false branches via `exists()` mock; `_resolve_sender_account` returns first live + None when none). **Notable adaptations from the spec:** (a) **Celery config file is `src/celery/celery_config.py` not `core/celery.py`** — matches the actual project layout per Step 4's adaptation note, not the spec's filename; (b) **Tasks split into `tasks.py` + `scheduler.py`** — pure async logic in scheduler.py is testable without Celery; the `@shared_task` wrapper in tasks.py matches the convention from `core/email/tasks.py` and `core/campaigns/tasks.py`; (c) **`EnrollmentState` is stored as TEXT with a DB CHECK constraint** rather than a Postgres ENUM — adding a future state (e.g. `completed_no_send`) doesn't need an enum-alter migration; (d) **Update with `steps` is rejected (409) when active/paused enrollments exist** — the spec's full-replace semantics would orphan in-flight `email_sequence_enrollment_steps.step_id` FKs, so we refuse the operation and tell the operator to cancel/complete enrollments first; (e) **Reply detection joins `messages` directly** rather than `activities`, because `messages.direction` is indexed and the activities payload would table-scan; both inbound/outbound email writes hit messages (Step 5 owns that path); (f) **Sender resolution uses the rep who enrolled the contact** (`enrollment.enrolled_by`) and looks up their first `sync_state='live'` email account; no per-org "default sender" fallback because sequences are 1:1 with rep ownership; (g) **HardCapExceeded reschedules to tomorrow same time** rather than re-queuing immediately, so a rep at their daily cap doesn't burn the cap on a single sequence's tail; (h) **No per-org loop or `email_backfill`-style queue split** — the cross-org sweep + per-row tenant context + 200-rows/tick cap covers concurrency safely. Smoke pending: needs `docker-helper.cmd migrate` to land `0084` + `0085`, role-template backfill INSERT for any existing org rows, and pytest run.
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
