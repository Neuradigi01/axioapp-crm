# Step 1 — Event bus and automation schema

**Goal:** Land the foundation — an in-process pub/sub event bus + the `tbl_automation_triggers` / `tbl_automation_runs` tables with RLS, SQLAlchemy models, and Pydantic schemas. No domain events publish yet; no triggers fire yet.
**Status:** COMPLETED — Migration `0126_automation_schema` written (full table+enum+RLS DDL in a single reversible upgrade/downgrade pair). Creates `tbl_automation_triggers` (id, org_id, name, enabled, event_type text, conditions JSONB default `{}`, channel via the existing `conversation_channel` PG enum, template_id FK `tbl_message_templates ON DELETE RESTRICT`, delay_seconds, recipient_resolver + recipient_resolver_config JSONB, audit cols) + `tbl_automation_runs` (status via new `automation_run_status` enum with values `queued/dispatched/sent/failed/skipped`, trigger_id CASCADE FK, contact_id SET-NULL FK, event_payload JSONB, channel_message_id text, error text, scheduled_at/dispatched_at/completed_at). Indexes: `(org_id, event_type, enabled)` for the matcher; `(trigger_id, scheduled_at DESC)` for the run-history view; partial `(org_id, status, scheduled_at) WHERE status IN ('queued','dispatched')` for the dispatcher sweep; functional unique `(org_id, lower(name))` on triggers. RLS enabled + forced on both tables with `tenant_isolation_*` policies keyed on `app.org_id` GUC. NEW `core/events/__init__.py` + `core/events/bus.py` — process-local pub/sub: `subscribe(event_type, handler)` (idempotent on same handler), `unsubscribe`, `async publish(event_type, payload, *, org_id)` (merges org_id + event_type into the envelope, awaits coroutine and sync handlers, swallows + logs per-handler exceptions so one bad subscriber doesn't poison the rest, no-op when no subscribers registered). Full event-type taxonomy documented in the `bus.py` module docstring (`user.signed_up`, `lead.created`, `appointment.booked`, …). NEW `core/automation/__init__.py` (docstring only) + `core/automation/models.py` (`AutomationTrigger`, `AutomationRun`, `AutomationRunStatus` enum, both models inherit `TenantScoped` so the `do_orm_execute` listener auto-injects the org_id WHERE clause) + `core/automation/schemas.py` (`TriggerCreate` / `TriggerUpdate` / `TriggerRead` / `RunRead`; PATCH allows toggling just `enabled` without re-supplying name/channel/template_id; delay_seconds clamped to `[0, 30 days]`). NEW `core/automation/data_access.py` as a single empty placeholder file (locked layered-architecture convention per CLAUDE.md + memory `feedback_backend_layered_architecture.md` — single file, NOT a `data_access/` folder; deviates from this step's MD which still mentions the folder layout from the older 2026-06-23 convention; Step 2 + Step 4 fill in the actual query bodies). 12 pytest cases across `test_models_import.py` (6 — TenantScoped inheritance, enum values, Base.metadata registration, TriggerCreate round-trip, negative-delay rejection, TriggerUpdate all-optional) + `test_event_bus.py` (6 — subscribe-then-publish envelope shape, multiple subscribers each fire, no-subscribers no-op, handler exception swallowed + next fires, idempotent re-subscribe, unsubscribe removes). **Migration apply DEFERRED — the remote DB at `145.223.21.204:8975` dropped the connection mid-transaction on three consecutive attempts (asyncpg `ConnectionDoesNotExistError` during CREATE INDEX once, two timeouts during connect). Each attempt rolled back cleanly — alembic head still reports `0125_review_external_sync`. Re-run `API/run.cmd upgrade` from a fresh terminal when the DB is responsive again; the migration is idempotent and ready to apply.** Pytest run also deferred per `feedback_pause_before_pytest.md` baseline.
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

0. **Data-access layer** (project convention): create `core/automation/data_access/` from day one with two sub-files —
   - `triggers.py` (placeholder for Step 2's match_triggers / list / get).
   - `runs.py` (placeholder for Step 4's idempotency check by `(trigger_id, event_id)` + run-history reads).
   - `__init__.py` re-exports both. Step 2 + Step 4 fill in the actual query bodies; Step 1 lands the empty package so the convention is in place from the first commit.
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
