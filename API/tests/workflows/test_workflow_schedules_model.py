"""Pin tests for the Step-1 workflow-scheduling model additions.

Covers, without touching a database:

  * ``WorkflowSchedule`` imports cleanly + inherits ``TenantScoped``.
  * ``WorkflowSchedule`` registers with ``Base.metadata``.
  * The four scheduling enums + ``TriggerKind`` carry the values the
    Step-1 spec documents (any drift breaks migration 0182 + the
    Step-3 API validators).
  * ``WorkflowRun`` gained the three audit columns.

DB-touching tests live in ``test_workflow_schedules_dal.py`` — kept
apart because pin tests should stay pytest-fast (per memory:
pytest takes ~12 min in this repo).
"""

from __future__ import annotations

from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    DeactivationReason,
    OnMissedPolicy,
    ScheduleKind,
    TriggerKind,
    WorkflowRun,
    WorkflowSchedule,
)
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


def test_workflow_schedule_inherits_tenant_scoped():
    """RLS + auto-org_id filter MUST apply to schedules."""
    assert issubclass(WorkflowSchedule, TenantScoped), (
        "WorkflowSchedule must inherit TenantScoped (RLS gate)"
    )


def test_workflow_schedule_registered_with_base_metadata():
    """Model must be discoverable via ``Base.metadata.tables`` so
    Alembic autogenerate + the test-DB fixture pick it up."""
    assert "tbl_workflow_schedules" in Base.metadata.tables


def test_workflow_schedules_table_has_partial_index():
    """Sweep hot path — partial index on ``next_run_at WHERE
    active=true`` MUST exist on the table definition."""
    table = Base.metadata.tables["tbl_workflow_schedules"]
    idx_names = {ix.name for ix in table.indexes}
    assert "ix_schedules_next_run_due" in idx_names, f"missing partial index; got {idx_names}"
    assert "ix_schedules_org_workflow" in idx_names, (
        f"missing (org_id, workflow_id) index; got {idx_names}"
    )


def test_schedule_kind_enum_values():
    assert {m.value for m in ScheduleKind} == {
        "once",
        "daily",
        "weekly",
        "monthly",
        "interval",
        "cron",
    }


def test_on_missed_policy_enum_values():
    assert {m.value for m in OnMissedPolicy} == {
        "skip",
        "run_once",
        "backfill_all",
    }
    # Default per README locked decisions.
    assert OnMissedPolicy.skip.value == "skip"


def test_concurrency_policy_enum_values():
    assert {m.value for m in ConcurrencyPolicy} == {
        "allow",
        "forbid",
        "replace",
    }
    # Default per README locked decisions — matches k8s CronJob.
    assert ConcurrencyPolicy.forbid.value == "forbid"


def test_deactivation_reason_enum_values():
    assert {m.value for m in DeactivationReason} == {
        "manual",
        "ended",
        "max_runs",
        "end_at",
        "consecutive_empty",
        "recurrence_timeout",
        "recurrence_invalid",
        "contact_deleted",
        "admin_edit_past_end_at",
    }


def test_trigger_kind_enum_values():
    assert {m.value for m in TriggerKind} == {
        "event",
        "schedule",
        "manual",
    }


def test_workflow_run_has_new_audit_columns():
    """The three audit columns added by migration 0182 must be
    present on the ORM model too (Alembic + ORM must agree)."""
    columns = {c.name for c in WorkflowRun.__table__.columns}
    assert "trigger_kind" in columns
    assert "trigger_source_id" in columns
    assert "triggered_by_user_id" in columns


def test_workflow_schedule_columns_present():
    """Full column shape must match the Step-1 spec so downstream
    code (service, sweep, API) can reference every field."""
    columns = {c.name for c in WorkflowSchedule.__table__.columns}
    expected = {
        "id",
        "org_id",
        "workflow_id",
        "contact_id",
        "name",
        "schedule_kind",
        "config_json",
        "timezone",
        "starts_at",
        "end_at",
        "next_run_at",
        "last_run_at",
        "runs_completed",
        "max_runs",
        "active",
        "deactivation_reason",
        "on_missed",
        "concurrency_policy",
        "consecutive_empty_fires",
        "created_by_user_id",
        "created_at",
        "updated_at",
    }
    missing = expected - columns
    assert not missing, f"WorkflowSchedule missing columns: {missing}"


def test_workflow_schedule_contact_id_is_nullable():
    """Nullable ``contact_id`` is load-bearing — NULL means "fire
    without a contact dimension" (e.g. daily notify-admin) and the
    column shape lets a future date-anchored-trigger track fire per-
    contact without a table split."""
    col = WorkflowSchedule.__table__.columns["contact_id"]
    assert col.nullable is True


def test_workflow_schedule_workflow_fk_cascades():
    """Deleting the parent workflow must cascade — no orphan
    schedules."""
    fks = list(WorkflowSchedule.__table__.columns["workflow_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "CASCADE"


def test_workflow_schedule_org_fk_cascades():
    """Deleting the parent org must cascade — matches every other
    tenant-scoped table."""
    fks = list(WorkflowSchedule.__table__.columns["org_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "CASCADE"


def test_workflow_schedule_contact_fk_set_null():
    """Contact hard-delete sets FK NULL; Step-6 will then
    deactivate the schedule with reason=contact_deleted. Two-step
    cascade is intentional so the trigger fires from service code
    (audit + email), not silently from the DB."""
    fks = list(WorkflowSchedule.__table__.columns["contact_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "SET NULL"
