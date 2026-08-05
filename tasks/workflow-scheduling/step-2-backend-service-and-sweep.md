# Step 2 — Backend service + extend `sweep_waits` + dual-dispatch + null-contact action audit

**Goal:** Land the recurrence math (via `croniter` + `zoneinfo`), extend the existing `sweep_waits` beat task to also pick due schedule rows, wire dual-dispatch (publish `workflow.schedule_fired` event + call `engine.start_run`), and audit every action handler for `contact_id=None` safety. After Step 2, hand-crafted schedule rows fire on time.

**Status:** Pending

**Depends on:** Step 1 (model + DAL + croniter dep)

---

## Scope

**In-scope:**
- `core/workflows/service.py` additions:
  - `compute_next_run_at(schedule, *, now)` — pure function; branches on `schedule_kind`; uses `zoneinfo` + `croniter`; 500ms hard timeout (`_croniter_timeout_wrapper` shared utility).
  - `create_schedule_service`, `update_schedule_fields_service`, `pause_schedule_service`, `resume_schedule_service`, `delete_schedule_service` (service layer only; endpoints in Step 3).
  - `_dispatch_due_schedule(db, schedule)` — per-schedule dispatch: RLS context set, savepoint, concurrency-policy check, on_missed handling, event publish, `engine.start_run` call, `next_run_at` advance + `consecutive_empty_fires` update, deactivation on terminal conditions, all inside one transaction with a savepoint. Emits `schedule.missed_fire` audit event when forward-compute skips ≥1 fire.
  - `_fire_budget_check(db, org_id, now)` — per-org fires-per-hour cap; skip + `schedule.rate_limited` audit event when exceeded.
- `core/workflows/tasks.py`: extend `sweep_waits` to also call a new `service.sweep_due_schedules()`. Same 60s cadence, same worker. NO new beat entry.
- `core/events/event_catalog.py`: add `WORKFLOW_SCHEDULE_FIRED = "workflow.schedule_fired"`; register in `ALL_EVENTS`.
- `core/workflows/trigger_handlers.py`: subscribe `workflow.schedule_fired` for observability (audit, future). This subscriber does NOT re-fire the workflow (dispatch is direct); it only writes audit rows.
- `core/workflows/actions/` — **audit every handler** in `send.py`, `records.py`, `lifecycle.py`, `flow_control.py`, `routing.py`, `tagging.py` for `contact_id=None` behavior. Handlers requiring a contact raise `ActionRequiresContactError` (new exception in `core/workflows/exceptions.py`); engine catches → marks run `errored` with the specific handler ID as `error_reason`. Handlers that don't need a contact (e.g. `notify.admin`, `create-task`, `webhook.call`) explicitly documented + tested.
- Utility: `core/workflows/_croniter_timeout.py` — 500ms compute timeout wrapper (`signal.alarm` on POSIX; falls back to `concurrent.futures` with 500ms `.result()` timeout for portability).
- Tests: sweep behavior, dispatch semantics, recurrence math (DST cases), missed-run policy, concurrency-policy, per-row savepoint, null-contact handler matrix.

**Out-of-scope:**
- HTTP endpoints (Step 3).
- ETag/If-Match (Step 3).
- Frontend (Steps 4/5).
- Contact-merge cascade + orphan reaper (Step 6).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/workflows/service.py` | edit — add schedule CRUD service methods + `sweep_due_schedules` + `_dispatch_due_schedule` + `compute_next_run_at` + `_fire_budget_check` |
| `api/src/app/core/workflows/tasks.py` | edit — extend `sweep_waits` async body to also call `service.sweep_due_schedules()` |
| `api/src/app/core/workflows/_croniter_timeout.py` | **NEW** — 500ms timeout wrapper utility (~40 lines) |
| `api/src/app/core/workflows/exceptions.py` | edit — add `ActionRequiresContactError` |
| `api/src/app/core/workflows/actions/*.py` | edit — audit every handler; raise `ActionRequiresContactError` where a contact is required; add unit-testable `handler_requires_contact: bool` metadata |
| `api/src/app/core/events/event_catalog.py` | edit — add `WORKFLOW_SCHEDULE_FIRED` |
| `api/src/app/core/workflows/trigger_handlers.py` | edit — subscribe `workflow.schedule_fired` for audit-only (no re-fire) |
| `api/tests/workflows/test_schedule_dispatch.py` | **NEW** — sweep tests: due picking, SKIP LOCKED, savepoint isolation, event publish, start_run call, RLS-in-Celery |
| `api/tests/workflows/test_schedule_recurrence.py` | **NEW** — recurrence math: 6 presets × edge cases (DST spring/fall, day-31 clamp, monthly nth-weekday, cron re-parse on load, timeout deactivates) |
| `api/tests/workflows/test_schedule_lifecycle.py` | **NEW** — on_missed × 3, concurrency × 3, max_runs, end_at, consecutive_empty, rate-limit skip |
| `api/tests/workflows/test_action_null_contact_matrix.py` | **NEW** — one case per action handler proving null-contact behavior |

**~10 files, ~600 lines total.** Larger step — recurrence math + savepoint dispatch + null-contact audit are all load-bearing. If size review flags, split null-contact audit into 2a.

## Plan

1. **Recurrence math** — `compute_next_run_at` with all 6 kinds; local-tz math via `zoneinfo`, cron via `croniter.get_next(datetime, start_time=last_or_starts_at)`. Wrapped in timeout utility. Explicit DST test cases.
2. **Timeout utility** — shared `_croniter_timeout_wrapper(fn, args, kwargs, timeout_ms=500)`. Raises `TimeoutError` on breach. Test in isolation.
3. **Dispatch function** — single-schedule dispatch inside a per-row savepoint:
   - `SET LOCAL app.current_org_id = <schedule.org_id>` (RLS context for the enrolment).
   - Concurrency check: if `forbid` and prior run for `(workflow_id, contact_id, schedule_id)` is `running` → skip + advance `next_run_at`.
   - Fire-budget check (per-org fires/hour).
   - `on_missed` handling: count missed fires (`now - next_run_at` divided by cadence); if ≥1, write `schedule.missed_fire` audit; enqueue per policy.
   - Publish `workflow.schedule_fired` event.
   - `engine.start_run(workflow, contact_id, trigger_event_id=schedule_run_uuid)`.
   - Advance `next_run_at`; increment `runs_completed`; check terminal conditions (`max_runs`, `end_at`) → deactivate with reason.
   - Savepoint commits (or on raise: savepoint rolls back, `active=false` with `deactivation_reason='recurrence_timeout'` or `recurrence_invalid` written in an outer transaction, batch continues).
4. **Sweep integration** — `service.sweep_due_schedules()` walks `select_due_schedules_for_update_skip_locked` in bounded batches (100 per tick), dispatches each. Called from `sweep_waits` after wait-resume dispatch.
5. **Event catalog + trigger-handler subscription** — new event type; subscriber writes an `audit_event` row (existing pattern); does NOT call `start_run` (dispatch is direct — subscriber is observability only).
6. **Null-contact action audit** — read every handler in `actions/`; classify as contact-required vs contact-optional; add `requires_contact = True` metadata + raise-early on `contact_id=None`; document contact-optional handlers.
7. **Tests** — write from README §Tests list: sweep, recurrence, lifecycle, null-contact matrix. Aim for 40+ pytest cases in this step.

## DB changes / migrations

None — Step 2 is code-only. Step 1's migration is sufficient.

## Verification

- `uv run pytest api/tests/workflows/test_schedule_*` — all pass.
- `uv run pytest api/tests/workflows/test_action_null_contact_matrix.py` — all pass.
- Manual: `INSERT INTO tbl_workflow_schedules(...)` a `once` schedule with `next_run_at = now() + interval '90 seconds'`, `active=true`, `workflow_id` pointing at an existing active workflow → wait for two sweep ticks → verify `tbl_workflow_runs` has a new row with `trigger_kind='schedule'`, `trigger_source_id = <schedule id>`.
- Pin-tests: layering + `tbl_` naming both pass.
- Ruff clean.

## Stop-and-report template

```
Step 2 done — service + sweep + dual-dispatch + null-contact audit.

Files changed: <list>
What you can verify:
  - Hand-crafted schedule row with `next_run_at = now() + 90s` fires within 2 minutes
  - `tbl_workflow_runs` row has trigger_kind='schedule', trigger_source_id = the schedule id
  - `workflow.schedule_fired` event visible in audit log
  - Poison-row test: schedule with malformed config_json auto-deactivates with reason='recurrence_invalid', sweep continues (no batch rollback)
  - DST spring-forward + fall-back tests both pass
  - Null-contact matrix: 20+ handlers audited, contact-required handlers raise ActionRequiresContactError
Tests added: ~40
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean]
Awaiting your 'proceed' for Step 3.
```
