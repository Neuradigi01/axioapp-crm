# Step 5 — Trigger subscriptions + re-enrollment rules

**Goal:** Wire the workflows engine to the event bus from Module B (`core/events/bus.py`). On every published event, walk all enabled+active workflows whose trigger matches, evaluate the trigger node's conditions, check re-enrollment rules, and call `engine.start_run` for each matching workflow + contact. Pulls the shared event catalog into a single module both Module B and Module C reference.
**Status:** COMPLETED — NEW `core/events/event_catalog.py` declares 50+ event-type string constants grouped by domain (auth + onboarding, leads + contacts, sales, communications, activities, appointments + walk-ins, forms, campaigns + sequences, time-based) plus the canonical `ALL_EVENTS` tuple, `EVENT_DESCRIPTIONS` dict for the Step-14/15 trigger-event picker drawer, `is_known_event()` validator helper, and `list_descriptions()` for the editor's `GET /api/v1/workflows/event-catalog` (future endpoint). NEW `core/workflows/trigger_handlers.py` ships the universal `_on_event(envelope)` subscriber + `register_subscribers()` / `unregister_subscribers()` helpers. `_on_event` validates envelope shape, normalises org_id + contact_id from strings, queries `list_active_workflows_for_event(org_id, event_type)` (matcher hits the GIN index on `enabled_event_types`), and for every match calls `_maybe_start_run` which (a) checks idempotency via `find_existing_run(workflow_id, trigger_event_id)` and refuses replays, then (b) applies the re-enrollment rule (`once`/`daily`/`never`), then (c) calls `engine.start_run`. The matcher is wrapped in `RequestContext(org_id=...)` for the duration of the read so the `do_orm_execute` tenant filter applies; the per-workflow start_run call sets its own context internally. Re-enrollment rules per the spec: `once` refuses any non-canceled prior run for `(workflow, contact)`; `daily` refuses runs started ≥ today's UTC midnight; `never` always allows. Canceled prior runs never block — operators cancel + re-enrol freely (matches HubSpot's behaviour). Workflows with no `contact_id` in the envelope (e.g. `time.daily_tick`) bypass the re-enrollment check and always create a fresh run. A/B sibling split is a no-op placeholder (`_split_for_ab` returns the workflow unchanged); Step 18 will wire the 50/50 logic. `core/workflows/__init__.py` adds a side-effect call to `register_subscribers()` so subscribers register the moment the workflows package is imported — main.py's existing `import src.app.core.workflows.models` import chain pulls the package init in at app startup. `core/workflows/data_access.py` extended with `list_active_workflows_for_event(org_id, event_type)` (filters by status='active' + `enabled_event_types.any(event_type)` to hit the GIN index) and `find_existing_run(workflow_id, contact_id, since_started_at?, trigger_event_id?)` (three lookup modes: exact event_id replay-check; daily-window dedupe; once-rule dedupe — canceled runs excluded). `core/workflows/service.py` extended with `update_enabled_event_types_from_graph(org_id, workflow_id)` standalone helper that re-derives the denormalised column from the persisted graph + commits — same logic Step 2's `update_workflow` already runs inline on every graph patch, exposed standalone so a future repair script can fix drift. 6 pytest cases in `test_trigger_handlers.py`: catalog known_event sanity; subscribers idempotently registered (re-running register_subscribers doesn't double-add); `_on_event` starts a run for an active workflow with matching event_type + populates contact_id from the envelope; draft + paused workflows are skipped; cross-org isolation (event for org A doesn't fire org B's workflow); contactless events (time.daily_tick) create runs with `contact_id=NULL`; idempotent replay of same `event_id` produces exactly one row; `update_enabled_event_types_from_graph` rewrites a stale column from the persisted graph. 6 pytest cases in `test_reenrollment.py`: `once` refuses the second event for same (workflow, contact); `daily` refuses same-day repeats; `daily` allows after midnight via a back-dated prior row; `never` allows three back-to-back enrolments; canceled prior runs never block `once`; `find_existing_run` DAL hits + misses correctly on `trigger_event_id`. Pytest run deferred per `feedback_pause_before_pytest.md`. No migration needed — uses Step-1 schema.
**Depends on:** Step 4 (`engine.start_run`). `core/events/bus.py` from `tasks/automation-engine/` Step 1. Ideally Module B's Steps 5-6 have shipped (`user.signed_up` + `lead.created` publishers) — but workflows works even if no publishers exist yet; the subscriber just sits idle until events fire.

---

## Scope

In-scope:

- `core/events/event_catalog.py` (NEW — shared between Module B and Module C):
  - String constants for every event type the manager memory documents:
    - Auth + onboarding: `user.signed_up`, `user.invited`, `user.invitation_accepted`, `user.first_login`, `user.role_changed`.
    - Leads + contacts: `lead.created`, `lead.status_changed`, `lead.score_threshold`, `lead.assigned`, `lead.converted`, `lead.stale_7d / 30d / 90d`, `contact.created`, `contact.birthday`, `contact.anniversary`, `contact.opt_in_changed`.
    - Sales: `quote.sent / viewed / accepted / rejected / expired`, `invoice.sent / paid / overdue_7d / overdue_14d / overdue_30d`, `order.placed / delivered / refunded`.
    - Communications: `email.opened / clicked / replied`, `whatsapp.message_received / template_replied`.
    - Activities: `phone_call.logged`, `meeting.booked`, `task.created / assigned / completed / overdue`, `note.added`.
    - Appointments + walk-ins: `appointment.booked / reminder_24h / reminder_1h / completed / missed`, `walk_in.registered`.
    - Forms: `form.submitted`, `form.abandoned` (generic + per-form variants — the publisher emits both).
    - Campaigns + sequences: `campaign.sent`, `campaign.completed`, `sequence.completed`.
    - Time-based: `time.daily_tick` (org-local midnight).
  - Helper `is_known_event(event_type: str) -> bool` for the validator.
  - `EVENT_DESCRIPTIONS: dict[str, str]` mapping each constant to a one-line description — the Step 14/15 UI's node-config drawer uses this to render the trigger event picker.

- `core/workflows/trigger_handlers.py`:
  - Module-level side-effect import in `core/workflows/__init__.py` so subscribers register at app-start.
  - `async _on_event(envelope: dict)` — the universal subscriber. Registered for every event type via a loop over the catalog. Walks `tbl_workflows WHERE status='active' AND :event_type = ANY(enabled_event_types) AND org_id = envelope['org_id']`, evaluates the trigger node's `conditions` (Step 6 wires the evaluator; until then, `{}` means "always match"), checks re-enrollment, calls `engine.start_run`.
  - Subscriber registration uses Module B's `bus.subscribe(event_type, _on_event)`. Universal handler with per-event-type dispatch keeps the subscriber count constant (~30 events).

- Re-enrollment rules (per-workflow, set on `tbl_workflows.re_enrollment_rule`):
  - `once` (default): refuse start_run when a prior run exists for `(workflow_id, contact_id)`. Skip rows in terminal `archived / canceled` state — those don't block re-enrollment in the future-version-publishes-re-enrollment-eligible-contacts pattern.
  - `daily`: refuse when a run exists for `(workflow_id, contact_id, started_at >= today_org_tz)`.
  - `never`: always allow.

- `core/workflows/data_access.py` extended:
  - `list_active_workflows_for_event(session, *, org_id, event_type) -> list[Workflow]` — matcher query. Uses the `enabled_event_types` array index from Step 1 (`event_type = ANY(enabled_event_types)`).
  - `find_existing_run(session, *, workflow_id, contact_id, since_started_at=None) -> WorkflowRun | None` — re-enrollment dedupe.

- `core/workflows/service.py` extended:
  - `update_enabled_event_types_from_graph(session, workflow_id)` — called by `service.update_workflow` (Step 2 didn't ship it yet — this step adds the hook). Re-reads the graph's trigger nodes and rewrites `tbl_workflows.enabled_event_types` so the matcher's array filter stays in sync.

- Idempotency: `trigger_event_id` on the run row (from Step 1) — when present + non-null, `start_run` refuses to insert a duplicate row for the same `(workflow_id, contact_id, trigger_event_id)` triple. Publishers SHOULD pass a stable event id (e.g. the row PK of the originating record) — Module B's publishers will be retrofitted to do this when they ship.

Out of scope:

- Trigger conditions evaluation beyond "always match" — Step 6 ships the AST.
- Contact resolution from the event payload — the universal handler trusts the publisher to put `contact_id` in the envelope when there's a contact. No-contact events (e.g. `time.daily_tick`) start runs with `contact_id=NULL` and the workflow operates on org-level state.
- A/B split between two sibling workflows at enrollment time (Step 18 wires it — Step 5's `start_run` calls a placeholder `_split_for_ab(...)` that returns the workflow unchanged for now).
- Compliance gates (Step 12).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | **NEW** |
| `API/src/app/core/workflows/trigger_handlers.py` | **NEW** |
| `API/src/app/core/workflows/__init__.py` | edit — side-effect import the trigger handlers |
| `API/src/app/core/workflows/data_access.py` | edit — matcher + re-enrollment dedupe queries |
| `API/src/app/core/workflows/service.py` | edit — `update_enabled_event_types_from_graph` hook |
| `API/tests/workflows/test_trigger_handlers.py` | **NEW** |
| `API/tests/workflows/test_reenrollment.py` | **NEW** |

**~7 files. ~450 lines.**

## Plan

1. Event catalog — pure constants + descriptions. No DB.
2. Trigger handler module — universal `_on_event` subscriber + per-event-type dispatch.
3. DAL extensions — `list_active_workflows_for_event` + `find_existing_run`.
4. Service hook — `update_enabled_event_types_from_graph` called after every save.
5. Side-effect register the subscribers from the package init.
6. Tests: publish a synthetic event → run starts; re-publish same event → re-enrollment refusal (mode `once`); `daily` mode allows tomorrow's run; `never` mode allows back-to-back; idempotency on `trigger_event_id`.

## DB changes / migrations

None — uses tables + columns from Step 1.

## Tests

10 pytest cases:

- Subscribers register for every event in the catalog at module import.
- `_on_event` walks only active workflows for the right org + event type.
- Active workflow with empty trigger conditions: `start_run` invoked once.
- Re-enrollment `once`: second event for same contact → refused.
- Re-enrollment `daily`: second event same day → refused; next day → allowed.
- Re-enrollment `never`: second event → allowed; both runs progress in parallel.
- Workflow without `contact_id` in payload (e.g. `time.daily_tick`): run starts with `contact_id=NULL`.
- Different orgs same event: subscriber isolates by `org_id` (RLS belt + suspenders).
- Idempotent `trigger_event_id`: same event id replayed → no duplicate run row.
- `update_enabled_event_types_from_graph` rewrites the column on patch.

## Smoke

```
1. Create + activate a workflow: trigger(event_type='lead.created') → goal.
2. Python shell: await bus.publish("lead.created", {contact_id: ..., lead_id: ...}, org_id=...).
3. SELECT * FROM tbl_workflow_runs ORDER BY started_at DESC LIMIT 1 → status='completed', outcome='goal_reached'.
4. Re-publish the SAME event (same trigger_event_id) → no new run row.
5. Patch the workflow to switch trigger from lead.created → quote.sent; tbl_workflows.enabled_event_types updates.
6. Publish lead.created → no run starts (workflow no longer subscribes).
```

## Risks

- Universal subscriber subscribes to ~30 event types per app-start. Handler dispatch by event_type is O(1) (dict lookup). No measurable overhead.
- Re-enrollment dedupe race: two simultaneous events for the same `(workflow_id, contact_id)` — the DB unique constraint on `(workflow_id, contact_id, trigger_event_id)` (when both non-null) serializes; otherwise the dedupe check runs in the service-layer transaction and is best-effort.
- Idempotency window — once a run completes + the `trigger_event_id` exists in the historical run row, a republish months later still gets refused. This is intentional (matches HubSpot's behaviour). Operator can mark a contact "eligible" via a future support endpoint to bypass.

## Self-check (10 rules)

`core/workflows/` + `core/events/event_catalog.py`. ✓ org_id-scoped via RLS + explicit filter. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions reused. pack.yaml untouched. ✓ 7 files / ~450 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 5 — Trigger subscriptions + re-enrollment rules
Files: 7
Verify: event-bus subscriptions register for every catalog event; matching events start runs; re-enrollment honored for once/daily/never; idempotency on trigger_event_id.
Tests: 10 pytest cases.
Awaiting "proceed".
```
