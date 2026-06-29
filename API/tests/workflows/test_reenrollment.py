"""Pin tests for the Step-5 re-enrollment rules.

Covers the three rule modes per the spec:

  * ``once`` — first event for ``(workflow, contact)`` enrols;
    subsequent events for the same pair refuse silently.
  * ``daily`` — at most one enrolment per UTC calendar day per
    ``(workflow, contact)``.
  * ``never`` — every matching event creates a fresh run.

Plus:

  * Canceled prior runs never block re-enrollment (operator can
    re-enrol after cancellation).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.events.event_catalog import LEAD_CREATED
from src.app.core.workflows import (
    data_access as workflows_da,
    trigger_handlers,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _seed_workflow(
    test_db,
    *,
    org_id,
    re_enroll: WorkflowReEnrollmentRule,
) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph={
            "nodes": [
                {
                    "id": "t1",
                    "type": "trigger.lead_created",
                    "config": {"event_type": LEAD_CREATED},
                },
                {"id": "end", "type": "flow.end", "config": {}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "end"}],
        },
        enabled_event_types=[LEAD_CREATED],
        re_enrollment_rule=re_enroll,
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _make_contact(test_db, *, org_id) -> uuid.UUID:
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name) "
            "VALUES (:id, :org_id, :name)"
        ),
        {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
    )
    await test_db.commit()
    return contact_id


# ---------------------------------------------------------------------------
# `once` — first wins
# ---------------------------------------------------------------------------


async def test_re_enrollment_once_refuses_second_event(test_db, org_id):
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.once
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        for ev_id in ("first", "second"):
            await trigger_handlers._on_event(
                {
                    "event_type": LEAD_CREATED,
                    "org_id": org_id,
                    "event_id": ev_id,
                    "contact_id": str(contact_id),
                }
            )

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    # First enrolment was preserved — second was refused.
    assert rows[0].trigger_event_id == "first"


# ---------------------------------------------------------------------------
# `daily` — one per UTC day
# ---------------------------------------------------------------------------


async def test_re_enrollment_daily_refuses_same_day_repeat(test_db, org_id):
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.daily
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(
            {
                "event_type": LEAD_CREATED,
                "org_id": org_id,
                "event_id": "ev1",
                "contact_id": str(contact_id),
            }
        )
        await trigger_handlers._on_event(
            {
                "event_type": LEAD_CREATED,
                "org_id": org_id,
                "event_id": "ev2",
                "contact_id": str(contact_id),
            }
        )

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_re_enrollment_daily_allows_after_midnight(test_db, org_id):
    """A run from yesterday doesn't block today's enrolment under
    the daily rule. We simulate yesterday's run via a direct row
    insert + back-dated started_at."""
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.daily
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    # Yesterday's enrolment.
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    test_db.add(
        WorkflowRun(
            org_id=org_id,
            workflow_id=wf.id,
            version=1,
            contact_id=contact_id,
            trigger_event_id="yesterday-run",
            status=WorkflowRunStatus.completed,
            current_node_id=None,
            state={},
            started_at=yesterday,
        )
    )
    await test_db.commit()

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(
            {
                "event_type": LEAD_CREATED,
                "org_id": org_id,
                "event_id": "today-ev",
                "contact_id": str(contact_id),
            }
        )

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 2  # yesterday + today


# ---------------------------------------------------------------------------
# `never` — every event enrols
# ---------------------------------------------------------------------------


async def test_re_enrollment_never_allows_back_to_back(test_db, org_id):
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.never
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        for ev_id in ("ev1", "ev2", "ev3"):
            await trigger_handlers._on_event(
                {
                    "event_type": LEAD_CREATED,
                    "org_id": org_id,
                    "event_id": ev_id,
                    "contact_id": str(contact_id),
                }
            )

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Canceled prior runs don't block re-enrollment
# ---------------------------------------------------------------------------


async def test_canceled_prior_run_does_not_block_once(test_db, org_id):
    """The spec calls this out: canceled runs never block — operators
    cancel + re-enrol."""
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.once
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    test_db.add(
        WorkflowRun(
            org_id=org_id,
            workflow_id=wf.id,
            version=1,
            contact_id=contact_id,
            trigger_event_id="prior-canceled",
            status=WorkflowRunStatus.canceled,
            current_node_id=None,
            state={},
        )
    )
    await test_db.commit()

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(
            {
                "event_type": LEAD_CREATED,
                "org_id": org_id,
                "event_id": "fresh-ev",
                "contact_id": str(contact_id),
            }
        )

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    statuses = {r.status for r in rows}
    # The canceled row is preserved + a fresh row landed.
    assert WorkflowRunStatus.canceled in statuses
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# DAL helper sanity
# ---------------------------------------------------------------------------


async def test_find_existing_run_by_trigger_event_id_match(test_db, org_id):
    wf = await _seed_workflow(
        test_db, org_id=org_id, re_enroll=WorkflowReEnrollmentRule.never
    )
    contact_id = await _make_contact(test_db, org_id=org_id)

    test_db.add(
        WorkflowRun(
            org_id=org_id,
            workflow_id=wf.id,
            version=1,
            contact_id=contact_id,
            trigger_event_id="key-1",
            status=WorkflowRunStatus.completed,
            current_node_id=None,
            state={},
        )
    )
    await test_db.commit()

    hit = await workflows_da.find_existing_run(
        test_db,
        workflow_id=wf.id,
        contact_id=contact_id,
        trigger_event_id="key-1",
    )
    miss = await workflows_da.find_existing_run(
        test_db,
        workflow_id=wf.id,
        contact_id=contact_id,
        trigger_event_id="key-2",
    )
    assert hit is not None
    assert miss is None
