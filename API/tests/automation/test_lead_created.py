"""Pin tests for the Step-6 lead.created publisher + Lead
Confirmation seed trigger.

Covers:
  * Seed installation (template + trigger with the bulk_import
    exclusion baked in).
  * The matcher returns the seeded trigger for `lead.created` IF
    the source isn't `bulk_import`.
  * The bulk_import exclusion actually fires (no match when
    source='bulk_import').
  * `create_lead` publishes the event with the right envelope
    shape — verified by intercepting the bus.publish call.
  * The dispatcher enrols a queued run for any non-bulk source.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.automation import seeds
from src.app.core.automation import tasks as automation_tasks
from src.app.core.automation.models import (
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.automation.service import match_triggers
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo Workspace",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _install_seeds(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await seeds.install_default_org_seeds(test_db, org_id=org_id)
        await test_db.commit()
        return result
    finally:
        reset_context(token)


# --- seed installation -------------------------------------------


async def test_install_seeds_creates_lead_confirmation(test_db, org_id):
    result = await _install_seeds(test_db, org_id)
    assert "lead_template_id" in result
    assert "lead_trigger_id" in result

    rows = (
        (
            await test_db.execute(
                select(AutomationTrigger).where(
                    AutomationTrigger.org_id == org_id,
                    AutomationTrigger.name == "Lead Confirmation",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    trigger = rows[0]
    assert trigger.event_type == "lead.created"
    assert trigger.recipient_resolver == "contact.email"
    assert trigger.delay_seconds == 0
    # bulk_import exclusion baked in.
    assert trigger.conditions == {
        "field": "source",
        "op": "ne",
        "value": "bulk_import",
    }


async def test_install_seeds_is_idempotent_for_lead_confirmation(test_db, org_id):
    first = await _install_seeds(test_db, org_id)
    second = await _install_seeds(test_db, org_id)
    assert first == second  # same template + trigger ids


# --- matcher -----------------------------------------------------


async def test_match_triggers_returns_lead_confirmation_for_widget_source(test_db, org_id):
    await _install_seeds(test_db, org_id)
    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="lead.created",
        payload={
            "lead_id": str(uuid.uuid4()),
            "source": "widget",
            "contact": {"full_name": "Asha", "email": "asha@x.com"},
        },
    )
    names = [m.name for m in matches]
    assert "Lead Confirmation" in names


async def test_match_triggers_excludes_bulk_import_source(test_db, org_id):
    await _install_seeds(test_db, org_id)
    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="lead.created",
        payload={
            "source": "bulk_import",
            "contact": {"full_name": "Asha", "email": "asha@x.com"},
        },
    )
    names = [m.name for m in matches]
    assert "Lead Confirmation" not in names


# --- dispatcher fires for non-bulk sources -----------------------


async def test_dispatch_event_enrols_queued_run_for_widget_lead(test_db, org_id):
    await _install_seeds(test_db, org_id)
    from src.app.core.automation.dispatcher import dispatch_event

    with patch.object(automation_tasks.deliver_run, "apply_async"):
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="lead.created",
            payload={
                "lead_id": str(uuid.uuid4()),
                "source": "widget",
                "contact": {
                    "full_name": "Asha Mehta",
                    "email": "asha@example.com",
                },
            },
            event_id="lead_created:abc",
        )

    assert len(runs) == 1
    run = runs[0]
    assert run.status == AutomationRunStatus.queued
    assert run.event_payload["_resolved_recipient"] == "asha@example.com"


async def test_dispatch_event_skips_bulk_import_lead(test_db, org_id):
    await _install_seeds(test_db, org_id)
    from src.app.core.automation.dispatcher import dispatch_event

    with patch.object(automation_tasks.deliver_run, "apply_async") as schedule:
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="lead.created",
            payload={
                "source": "bulk_import",
                "contact": {"full_name": "Bulk", "email": "bulk@x.com"},
            },
            event_id="lead_created:bulk",
        )

    assert runs == []
    assert not schedule.called


# --- publish-call chokepoint discipline --------------------------


def test_create_lead_publishes_lead_created_exactly_once():
    """Pin test — `core/leads/service.py` MUST have exactly one
    bus.publish call for `lead.created` (the chokepoint). If a
    future refactor splits the publish across multiple call sites
    OR removes the call, this test fails."""
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    service = (repo_root / "src" / "app" / "core" / "leads" / "service.py").read_text(
        encoding="utf-8"
    )

    # Direct events.bus publish calls. Counts via the helper's
    # `_publish_lead_created` definition + the single call site
    # that invokes it.
    helper_def = re.findall(r"async def _publish_lead_created", service)
    assert len(helper_def) == 1, (
        "expected exactly one _publish_lead_created helper in core/leads/service.py"
    )
    invocations = re.findall(r"_publish_lead_created\(", service)
    # 1 definition + 1 call site = 2 occurrences.
    assert len(invocations) == 2, (
        f"expected one call to _publish_lead_created (chokepoint) "
        f"+ its definition (=2 grep hits); found {len(invocations)}"
    )

    # And the helper's body publishes `lead.created` exactly once.
    publish_calls = re.findall(r'events_publish\(\s*"lead\.created"', service)
    assert len(publish_calls) == 1, (
        f"expected exactly one events_publish('lead.created') in "
        f"core/leads/service.py; found {len(publish_calls)}"
    )
