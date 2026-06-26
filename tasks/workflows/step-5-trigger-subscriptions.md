# Step 5 — Trigger subscriptions + re-enrollment rules

**Goal:** Wire the workflows engine to the event bus from Module B (`core/events/bus.py`). On every published event, walk all enabled+active workflows whose trigger matches, evaluate the trigger node's conditions, check re-enrollment rules, and call `engine.start_run` for each matching workflow + contact. Pulls the shared event catalog into a single module both Module B and Module C reference.
**Status:** Pending
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
