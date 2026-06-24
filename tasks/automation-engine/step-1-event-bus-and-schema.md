# Step 1 — Event bus and automation schema

**Goal:** Land the foundation — an in-process pub/sub event bus + the `tbl_automation_triggers` / `tbl_automation_runs` tables with RLS, SQLAlchemy models, and Pydantic schemas. No domain events publish yet; no triggers fire yet.
**Status:** Pending
**Depends on:** `tasks/template-library/` fully shipped (so `tbl_message_templates` exists for FK target).

---

## Scope

In-scope:
- `core/events/bus.py`:
  - In-process pub/sub (process-local at v1; Redis fan-out deferred). Subscribers are coroutine functions registered at app start.
  - `publish(event_type: str, payload: dict, org_id: UUID)` — fire-and-forget; subscribers run via a Celery task per match to avoid blocking the publisher's transaction.
  - `subscribe(event_type: str, handler)` — registration helper called from module init.
  - Event-type taxonomy documented at the top of `bus.py` (`user.signed_up`, `lead.created`, `appointment.booked`, etc.) — only the strings; emit + subscribe lives in later steps.
- Migration `<ts>_automation_schema.py`:
  - `tbl_automation_triggers` — id, org_id, name, enabled, event_type text, conditions JSONB (default `{}`), channel (ConversationChannel enum), template_id UUID FK `tbl_message_templates(id) ON DELETE RESTRICT`, delay_seconds int default 0, recipient_resolver text (`contact.email | contact.phone | user.email | custom`), recipient_resolver_config JSONB (default `{}`), created_by_user_id, updated_by_user_id, timestamps. Unique `(org_id, lower(name))`.
  - `tbl_automation_runs` — id, org_id, trigger_id FK CASCADE, event_payload JSONB, contact_id UUID NULL (FK `tbl_contacts(id) SET NULL`), user_id UUID NULL (recipient if user-targeted), status enum (`queued | dispatched | sent | failed | skipped`), channel_message_id text nullable, error text nullable, scheduled_at timestamptz, dispatched_at timestamptz nullable, completed_at timestamptz nullable.
  - RLS on both tables.
  - Indexes: `(org_id, event_type, enabled)`, `(trigger_id, scheduled_at DESC)`, `(org_id, status, scheduled_at) WHERE status IN ('queued','dispatched')`.
- SQLAlchemy models: `AutomationTrigger`, `AutomationRun` extending `TenantScoped`.
- Pydantic schemas: `TriggerCreate`, `TriggerUpdate`, `TriggerRead`, `RunRead`.
- `core/automation/__init__.py`, `core/events/__init__.py` package docstrings.

Out of scope:
- Trigger service / router (Steps 2 + 3).
- Condition evaluator (Step 2).
- Event publishers (Steps 5 + 6 + 10 + 11 + 12).
- Dispatcher (Step 4).
- UI (Steps 7-9).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_automation_schema.py` | **NEW** |
| `API/src/app/core/events/__init__.py` | **NEW** — docstring |
| `API/src/app/core/events/bus.py` | **NEW** — pub/sub primitives |
| `API/src/app/core/automation/__init__.py` | **NEW** — docstring |
| `API/src/app/core/automation/models.py` | **NEW** — two SQLAlchemy classes |
| `API/src/app/core/automation/schemas.py` | **NEW** — Pydantic shapes |
| `API/tests/automation/__init__.py` | **NEW** — empty |
| `API/tests/automation/test_models_import.py` | **NEW** — import smoke |
| `API/tests/automation/test_event_bus.py` | **NEW** — pub/sub basic |

**~9 files. ~450 lines.**

## Plan

1. Migration: enum + two tables + RLS + indexes.
2. Event bus: minimal pub/sub primitives. Subscribers are registered at app-start (via module init); publish call queues a Celery task per matched subscriber so DB commits land first.
3. Models + schemas matching the migration verbatim.
4. Tests: import smoke + bus publishes-then-subscribes a single handler in-process.

## DB changes / migrations

Two new tables + one new enum (`automation_run_status`). Reversible.

## Tests

5 pytest cases:
- Models importable.
- `subscribe + publish` invokes the handler with the right payload.
- Multiple subscribers on the same event each fire.
- Subscribing on an unknown event-type string is allowed (forward-compatible) — handler simply never fires until something publishes.
- Tables RLS-isolated across orgs.

## Smoke

```
1. docker-helper.cmd upgrade head — migration applies.
2. \dt tbl_automation_* — two tables visible.
3. INSERT a trigger row + a run row via SQL with explicit org_id; SELECT confirms back.
4. Python shell: `from core.events.bus import publish, subscribe; subscribe("test.event", h); publish("test.event", {"x": 1}, org_id=...)` → handler fires with {"x": 1, "org_id": ...}.
5. uv run pytest API/tests/automation/ — green.
```

## Risks

- In-process bus + multi-worker uvicorn: each worker has its own bus instance. At v1 that's OK — subscribers fire via Celery anyway, so the bus only routes from "publish call" to "queue a Celery job". The actual handler runs in the Celery worker.
- Subscriber registration order matters at app start. Document in `bus.py` docstring: subscribers register at module-import time during FastAPI startup.

## Self-check (10 rules)

`core/events/` + `core/automation/`. ✓ org_id + RLS. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 7). N/A permissions (Step 3). pack.yaml untouched. ✓ 9 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 1 — Event bus and automation schema
Files: 9
Verify: pub/sub primitives + tables + models + schemas all importable; RLS isolates rows.
Tests: 5 pytest cases.
Awaiting "proceed".
```
