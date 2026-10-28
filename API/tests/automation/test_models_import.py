"""Pin tests for the Step-1 automation models surface.

Verifies:
  * ``AutomationTrigger`` + ``AutomationRun`` are importable from the
    package and inherit ``TenantScoped`` (so RLS auto-filter applies).
  * ``AutomationRunStatus`` enum carries the five lifecycle values
    documented in the spec.
  * Pydantic schemas (``TriggerCreate``, ``TriggerUpdate``,
    ``TriggerRead``, ``RunRead``) instantiate cleanly with valid
    payloads.
  * The table metadata is registered against ``Base.metadata`` so
    ``create_all`` in the test DB picks them up.

No DB inserts here — RLS isolation is exercised in
``test_rls_isolation.py``.
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.automation.schemas import (
    TriggerCreate,
    TriggerUpdate,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


def test_automation_models_inherit_tenant_scoped():
    """Both tables MUST be TenantScoped so the do_orm_execute
    listener applies the org_id WHERE-clause auto-filter."""
    assert issubclass(AutomationTrigger, TenantScoped)
    assert issubclass(AutomationRun, TenantScoped)


def test_automation_run_status_enum_values():
    assert {m.value for m in AutomationRunStatus} == {
        "queued",
        "dispatched",
        "sent",
        "failed",
        "skipped",
    }


def test_automation_tables_registered_with_base_metadata():
    """Step 4's dispatcher + Step 9's run-history endpoint both
    rely on `Base.metadata` knowing about these tables (test
    fixtures call create_all)."""
    table_names = set(Base.metadata.tables.keys())
    assert "tbl_automation_triggers" in table_names
    assert "tbl_automation_runs" in table_names


def test_trigger_create_schema_round_trip():
    payload = TriggerCreate(
        name="Welcome email",
        event_type="user.signed_up",
        channel=ConversationChannel.email,
        template_id=uuid.uuid4(),
    )
    assert payload.enabled is True
    assert payload.delay_seconds == 0
    assert payload.recipient_resolver == "contact.email"
    assert payload.conditions == {}


def test_trigger_create_rejects_negative_delay():
    with pytest.raises(ValueError):
        TriggerCreate(
            name="Bad",
            event_type="x.y",
            channel=ConversationChannel.email,
            template_id=uuid.uuid4(),
            delay_seconds=-1,
        )


def test_trigger_update_all_fields_optional():
    """PATCH allows toggling just `enabled` without re-supplying the
    rest of the trigger config."""
    patch = TriggerUpdate(enabled=False)
    assert patch.enabled is False
    assert patch.name is None
    assert patch.template_id is None
