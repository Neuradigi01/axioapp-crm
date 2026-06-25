# Step 4 — Dispatcher and Celery scheduling

**Goal:** Wire the event bus → trigger match → send pipeline. On event publish: enqueue a Celery task per matched trigger; the task resolves the recipient, renders the template, calls the channel adapter, and writes a `tbl_automation_runs` row. Honors `delay_seconds` via Celery `apply_async(countdown=...)`.
**Status:** Pending
**Depends on:** Step 1 (bus + schema), Step 2 (service + match + recipients), `tasks/template-library/` Step 5 (test-send dispatcher pattern reused).

---

## Scope

In-scope:
- `core/automation/dispatcher.py`:
  - `dispatch_event(org_id, event_type, payload)` — called by `bus.publish` once subscribers fire.
  - Loads matching triggers via `service.match_triggers(org_id, event_type, payload)`.
  - For each matched trigger: resolves recipient, inserts a `tbl_automation_runs` row with `status='queued'`, schedules the actual send via Celery `apply_async(countdown=trigger.delay_seconds)`.
  - If no recipient: writes a `skipped` run row with `error='no_recipient_resolved'`.
  - Idempotency: a `(trigger_id, event_id)` natural key in the run row prevents duplicate runs from the same event (event_id is supplied by the publisher).
- `core/automation/tasks.py`:
  - `automation.deliver_run(run_id)` — Celery task. Loads run + trigger + template, resolves variables via `core/templates/variables.resolve`, dispatches through the channel adapter (`core/conversations/adapters/...`), updates run row with `status='sent' | 'failed' | 'skipped'` + `channel_message_id` + `dispatched_at` + `completed_at` + `error`.
  - Autoretry policy: 3 attempts, exponential backoff on transient adapter failures. Permanent failures (invalid recipient, suppressed, template archived) skip retry.
- `core/events/bus.py` extension:
  - Built-in subscriber: `automation.dispatcher` subscribes to **every** event. (Wildcard subscription pattern — `subscribe_all(handler)`.)
  - `publish` writes the inbound event to a short-lived dedupe table or uses the natural key on `tbl_automation_runs` (`(trigger_id, event_id)` unique constraint) to absorb at-least-once delivery.
- Migration `<ts>_automation_runs_event_id.py`:
  - Adds `tbl_automation_runs.event_id text NOT NULL DEFAULT uuid_generate_v4()::text` (publisher-supplied event id).
  - Adds unique partial index `(trigger_id, event_id)` for idempotency.
- Re-uses the existing Celery scaffolding from `whatsapp-platform-upgrade` tasks (Beat schedule for periodic syncs comes later; for now `apply_async` is enough).

Out of scope:
- Frequency cap / quiet hours / suppression check (Step 13 — for now the dispatcher sends straight through).
- Bounce/complaint webhook handlers (Step 14).
- Sequence enrolment (out of this track entirely — future workflows track).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/dispatcher.py` | **NEW** |
| `API/src/app/core/automation/tasks.py` | **NEW** — Celery tasks |
| `API/src/app/core/events/bus.py` | edit — wildcard subscriber + event_id support in publish |
| `API/alembic/versions/<ts>_automation_runs_event_id.py` | **NEW** |
| `API/src/app/core/automation/models.py` | edit — `event_id` column + relationship |
| `API/src/app/core/automation/schemas.py` | edit — `RunRead.event_id` |
| `API/src/app/main.py` | edit — register the dispatcher's wildcard subscriber at app start |
| `API/tests/automation/test_dispatcher.py` | **NEW** |

**~8 files. ~500 lines.**

## Plan

0. **Data-access layer** (project convention) — Step 1 created `core/automation/data_access/runs.py`; this step fills it with:
   - `find_run_by_event_id(trigger_id, event_id) → AutomationRun | None` (idempotency check).
   - `list_runs(trigger_id, *, status?, since?, limit, offset)` for the future run-history UI (Step 9 reads via this).
   - `count_recent_marketing_sends_for_contact(contact_id, *, since)` placeholder for the Step-13 frequency-cap query.
   Dispatcher logic (load trigger → resolve recipient → schedule Celery task) + Celery task body (render + send + status update) stay in `dispatcher.py` / `tasks.py`. Cross-module reads (template lookup) go through `core/templates/data_access/templates.get_template(...)` — do NOT duplicate the query.
1. Migration: add event_id + unique index.
2. Dispatcher: pure function — load triggers, resolve recipients, schedule tasks.
3. Celery task: render via central template variables; send via channel adapter; update run row. Mock the adapter in tests.
4. Bus extension: wildcard subscriber so `dispatch_event` runs on every published event.
5. App startup: register the dispatcher.
6. Tests: publish event → expected run rows written + Celery task scheduled (use `apply_async` mock); delay honored; idempotency on duplicate event_ids; failed delivery writes `failed` status + error.

## DB changes / migrations

One migration — adds `event_id` + unique partial index. Reversible.

## Tests

10 pytest cases:
- `test_dispatch_event_writes_one_run_per_matched_trigger`
- `test_dispatch_event_skips_disabled_triggers`
- `test_dispatch_event_skips_if_no_recipient`
- `test_duplicate_event_id_does_not_create_second_run`
- `test_celery_task_renders_template_with_payload`
- `test_celery_task_sends_via_adapter`
- `test_celery_task_updates_status_to_sent_on_success`
- `test_celery_task_updates_status_to_failed_on_adapter_error`
- `test_celery_task_retries_on_transient_failure`
- `test_celery_task_does_not_retry_on_invalid_recipient`

## Smoke

```
1. Create a trigger pointing at an Email template with recipient_resolver=contact.email.
2. From a Python shell, publish a fake event matching its conditions.
3. SELECT * FROM tbl_automation_runs WHERE trigger_id=... → one row, status='queued', scheduled_at=now+delay.
4. Wait/advance for Celery to pick it up.
5. SELECT * → status='sent', channel_message_id populated, completed_at set.
6. Inbox of the resolved contact has the rendered email.
7. Publish the same event again with the same event_id → no new run row created (idempotency).
```

## Risks

- Wildcard subscriber on every event could become a hot path. At v1 it's a coroutine call + a DB read for matching triggers; OK at expected volumes. Revisit if needed.
- Celery task delivery rate must accommodate burst events (e.g., bulk import publishes 1000 lead.created events). Default broker config + 4 workers handles ~100/sec — acceptable.
- Idempotency relies on publishers passing a stable `event_id`. Document in `bus.py`: publishers SHOULD pass `event_id`; if omitted, a fresh UUID is generated and idempotency is per-fire (no dedupe). Native modules pass deterministic event_ids in Steps 5/6.

## Self-check (10 rules)

`core/automation/`. ✓ org_id propagated through every step. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already in place. ✓ pack.yaml untouched. ✓ 8 files / ~500 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 4 — Dispatcher and Celery scheduling
Files: 8
Verify: publish event → matched triggers schedule Celery tasks → tasks send + update run rows. Delay honored. Idempotent on duplicate event_id.
Tests: 10 pytest cases.
Awaiting "proceed".
```
