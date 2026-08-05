# Step 1 — Backend model + migration + DAL + `croniter` dep

**Goal:** Land the `tbl_workflow_schedules` table, add audit columns to `tbl_workflow_runs`, backfill `org.timezone` NULLs, add `croniter` dependency, ship pure DAL CRUD + due-query. No service logic, no endpoints, no engine wiring yet.

**Status:** COMPLETED (2026-08-05, migration `0182_workflow_schedules` applied to dev DB; up + down + re-up verified clean; ruff clean; 166 pre-existing runs backfilled to `trigger_kind='event'`; DAL/model tests written, pytest run pending user go-ahead per memory)

**Depends on:** `core/workflows/` (live), `core/tenants/` (live), `core/contacts/` (live)

---

## Scope

**In-scope:**
- `WorkflowSchedule` SQLAlchemy model (5-file layout: extends `core/workflows/models.py`).
- Three new enums: `ScheduleKind`, `OnMissedPolicy`, `ConcurrencyPolicy`, `DeactivationReason` (see README locked decisions).
- Audit columns on `WorkflowRun`: `trigger_kind`, `trigger_source_id`, `triggered_by_user_id`.
- One Alembic migration:
  1. Create `tbl_workflow_schedules` with partial index `ix_schedules_next_run_due ON tbl_workflow_schedules (next_run_at) WHERE active = true`.
  2. Add `trigger_kind`, `trigger_source_id`, `triggered_by_user_id` columns to `tbl_workflow_runs`; backfill existing rows to `trigger_kind='event'`.
  3. Backfill `tbl_organizations.timezone` NULLs → `'UTC'`.
  4. RLS policy on `tbl_workflow_schedules` matching existing workflow-table policies.
- Pure DAL functions in `core/workflows/data_access.py`: `insert_schedule`, `get_schedule_by_id_and_org`, `list_schedules_for_workflow`, `list_active_schedules_for_org`, `update_schedule_fields`, `delete_schedule`, `select_due_schedules_for_update_skip_locked`, `select_orphaned_pending_runs`, `count_active_schedules_for_org`, `get_workflow_by_id_and_org` (reusable cross-module load-and-check).
- `croniter` added to `api/pyproject.toml` (pinned major, e.g. `croniter>=2.0,<3.0`); `uv sync` run.
- Pytest: model + migration integrity only (no service tests yet).

**Out-of-scope** (later steps):
- Recurrence math (Step 2).
- Sweep integration (Step 2).
- API endpoints (Step 3).
- Frontend (Step 4).
- Contact-merge cascade (Step 6).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/workflows/models.py` | edit — add 4 enums + `WorkflowSchedule` model + 3 audit columns on `WorkflowRun` |
| `api/src/app/core/workflows/data_access.py` | edit — add 10 CRUD/query functions listed above |
| `api/alembic/versions/0178_workflow_schedules.py` | **NEW** — migration (revision ID = `0178_workflow_schedules`, 22 chars, ≤32) |
| `api/pyproject.toml` | edit — add `croniter>=2.0,<3.0` under `[project.dependencies]` |
| `api/tests/workflows/test_workflow_schedules_model.py` | **NEW** — 6 cases: model instantiates, FK cascade to workflow, FK cascade to org, RLS filters cross-org, partial index present, migration up/down clean |
| `api/tests/workflows/test_workflow_schedules_dal.py` | **NEW** — 8 cases: CRUD roundtrip, `select_due_schedules` returns due-only, `SKIP LOCKED` under concurrent tx, `count_active_schedules_for_org` honors partial-index semantics, `get_workflow_by_id_and_org` returns None on cross-org, `select_orphaned_pending_runs` returns >1h-old only |

**~6 files, ~450 lines.** At the split threshold — if it grows past ~500 lines during implementation, split the DAL functions into Step 1a/1b.

## Model surface

```python
class ScheduleKind(str, enum.Enum):
    once = "once"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    interval = "interval"
    cron = "cron"

class OnMissedPolicy(str, enum.Enum):
    skip = "skip"
    run_once = "run_once"
    backfill_all = "backfill_all"

class ConcurrencyPolicy(str, enum.Enum):
    allow = "allow"
    forbid = "forbid"
    replace = "replace"

class DeactivationReason(str, enum.Enum):
    manual = "manual"
    ended = "ended"
    max_runs = "max_runs"
    end_at = "end_at"
    consecutive_empty = "consecutive_empty"
    recurrence_timeout = "recurrence_timeout"
    recurrence_invalid = "recurrence_invalid"
    contact_deleted = "contact_deleted"
    admin_edit_past_end_at = "admin_edit_past_end_at"

class WorkflowSchedule(Base, TenantScoped):
    __tablename__ = "tbl_workflow_schedules"
    id: Mapped[uuid.UUID]                # pk, default uuid4
    org_id: Mapped[uuid.UUID]            # FK tbl_organizations, ondelete CASCADE, indexed
    workflow_id: Mapped[uuid.UUID]       # FK tbl_workflows, ondelete CASCADE, indexed
    contact_id: Mapped[uuid.UUID | None] # FK tbl_contacts, ondelete SET NULL, nullable
    name: Mapped[str]                    # operator label, max 200
    schedule_kind: Mapped[ScheduleKind]
    config_json: Mapped[dict]            # JSONB, kind-specific
    timezone: Mapped[str]                # IANA tz string, default org.timezone or 'UTC'
    starts_at: Mapped[datetime]          # UTC
    end_at: Mapped[datetime | None]      # UTC
    next_run_at: Mapped[datetime | None] # UTC, NULL when inactive/ended
    last_run_at: Mapped[datetime | None] # UTC
    runs_completed: Mapped[int]          # default 0
    max_runs: Mapped[int | None]
    active: Mapped[bool]                 # default True
    deactivation_reason: Mapped[DeactivationReason | None]
    on_missed: Mapped[OnMissedPolicy]    # default skip
    concurrency_policy: Mapped[ConcurrencyPolicy]  # default forbid
    consecutive_empty_fires: Mapped[int] # default 0
    created_by_user_id: Mapped[uuid.UUID | None]  # FK tbl_users, ondelete SET NULL
    created_at: Mapped[datetime]         # UTC, server_default now()
    updated_at: Mapped[datetime]         # UTC, server_default now(), auto-updated (ETag source)

    __table_args__ = (
        Index("ix_schedules_next_run_due", "next_run_at",
              postgresql_where=text("active = true")),
        Index("ix_schedules_org_workflow", "org_id", "workflow_id"),
        {"schema": None},  # RLS enabled below
    )

# --- Additions to existing WorkflowRun -----------------------------------
class TriggerKind(str, enum.Enum):
    event = "event"
    schedule = "schedule"
    manual = "manual"

# WorkflowRun gets:
#   trigger_kind: Mapped[TriggerKind]        # default event (backfilled)
#   trigger_source_id: Mapped[uuid.UUID | None]  # schedule_id or event_id
#   triggered_by_user_id: Mapped[uuid.UUID | None]  # for manual
```

## Migration (`0178_workflow_schedules`)

1. `CREATE TYPE` for the 5 enums.
2. `CREATE TABLE tbl_workflow_schedules` with columns above.
3. `CREATE INDEX ix_schedules_next_run_due ... WHERE active = true` (partial).
4. `CREATE INDEX ix_schedules_org_workflow ...`.
5. `ALTER TABLE tbl_workflow_runs ADD COLUMN trigger_kind workflow_trigger_kind NOT NULL DEFAULT 'event'`, `ADD COLUMN trigger_source_id uuid`, `ADD COLUMN triggered_by_user_id uuid REFERENCES tbl_users(id) ON DELETE SET NULL`.
6. `UPDATE tbl_organizations SET timezone = 'UTC' WHERE timezone IS NULL` (one-time repair).
7. RLS policy: `CREATE POLICY workflow_schedules_isolation ON tbl_workflow_schedules USING (org_id = current_setting('app.current_org_id')::uuid)`; `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`.

Downgrade: drop policy → drop columns from `tbl_workflow_runs` → drop `tbl_workflow_schedules` → drop enum types. `org.timezone` backfill is NOT reversed (no data to reverse to).

## Verification

- `uv run alembic upgrade head` — migration applies clean.
- `uv run alembic downgrade -1` — clean downgrade.
- `uv run alembic upgrade head` — re-apply, still clean (idempotent).
- Pin-tests: `test_table_name_convention.py` and `test_layered_architecture_convention.py` both pass.
- `uv run pytest api/tests/workflows/test_workflow_schedules_model.py api/tests/workflows/test_workflow_schedules_dal.py` — all pass.
- `uv run ruff check` + `uv run ruff format --check` clean on touched files.

## Stop-and-report template

```
Step 1 done — backend model + migration + DAL + croniter dep.

Files changed: <list>
What you can verify:
  - `uv run alembic current` shows 0178_workflow_schedules
  - `\d tbl_workflow_schedules` in psql shows the columns + partial index
  - `\d tbl_workflow_runs` shows the 3 new audit columns
  - `SELECT COUNT(*) FROM tbl_organizations WHERE timezone IS NULL` returns 0
  - `uv run pytest api/tests/workflows/test_workflow_schedules_*` passes
Tests added: 14
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean]
Awaiting your 'proceed' for Step 2.
```
