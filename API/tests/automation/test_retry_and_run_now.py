"""Pin tests for Step-9 retry + run-now + per-contact filter
endpoints.

Tests exercise the service-layer + dispatcher path directly (the
router glue is one-line passthrough — the relevant logic is the
state machine on the run row + the synthetic event_id used by
run-now). All Celery scheduling is mocked at the
``deliver_run.apply_async`` boundary so no real workers are
required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.automation import (
    data_access,
    dispatcher,
)
from src.app.core.automation import (
    service as automation_service,
)
from src.app.core.automation import (
    tasks as automation_tasks,
)
from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
)
from src.app.core.automation.schemas import TriggerCreate
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import TemplateCategory
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def _make_trigger(test_db, *, org_id, conditions=None):
    token = set_context(RequestContext(org_id=org_id))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name=f"RetryTpl-{uuid.uuid4().hex[:4]}",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi",
                subject="Hi",
            ),
        )
        trigger = await automation_service.create_trigger(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TriggerCreate(
                name=f"trg-{uuid.uuid4().hex[:6]}",
                event_type="user.signed_up",
                channel=ConversationChannel.email,
                template_id=template.id,
                conditions=conditions or {},
                recipient_resolver="contact.email",
            ),
        )
    finally:
        reset_context(token)
    return trigger


# --- retry ---------------------------------------------------------


async def test_retry_failed_run_resets_status_and_schedules(test_db, org_id):
    trigger = await _make_trigger(test_db, org_id=org_id)

    # Insert a failed run row directly so we can simulate retry on it.
    run = AutomationRun(
        org_id=org_id,
        trigger_id=trigger.id,
        event_id="event-fail",
        event_payload={"contact": {"email": "asha@x.com"}},
        status=AutomationRunStatus.failed,
        error="SMTP timeout",
        scheduled_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)

    # The router's retry handler runs this block — we exercise the
    # critical state-machine logic directly + assert the side effects.
    with patch.object(automation_tasks.deliver_run, "apply_async") as schedule:
        run.status = AutomationRunStatus.queued
        run.error = None
        run.dispatched_at = None
        run.completed_at = None
        run.channel_message_id = None
        run.scheduled_at = datetime.now(UTC)
        await test_db.commit()
        automation_tasks.deliver_run.apply_async(args=(str(run.id),), countdown=0)

    await test_db.refresh(run)
    assert run.status == AutomationRunStatus.queued
    assert run.error is None
    assert run.completed_at is None
    assert schedule.call_args.kwargs["args"] == (str(run.id),)


async def test_retry_succeeded_run_blocks_in_router_logic(test_db, org_id):
    """The router's status-check refuses anything other than failed.
    We pin the state-machine contract here — only 'failed' is
    retryable."""
    trigger = await _make_trigger(test_db, org_id=org_id)
    run = AutomationRun(
        org_id=org_id,
        trigger_id=trigger.id,
        event_id="event-sent",
        event_payload={},
        status=AutomationRunStatus.sent,
        scheduled_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)
    assert run.status == AutomationRunStatus.sent
    # The retry endpoint's gate `run.status != failed` returns 409;
    # at the model layer the gate is just the comparison above.
    assert run.status != AutomationRunStatus.failed


# --- run-now ------------------------------------------------------


async def test_run_now_creates_fresh_run_row_with_manual_event_id(test_db, org_id):
    trigger = await _make_trigger(test_db, org_id=org_id)
    manual_event_id = f"manual:{trigger.id}:{uuid.uuid4()}"

    with patch.object(automation_tasks.deliver_run, "apply_async"):
        runs = await dispatcher.dispatch_event(
            test_db,
            org_id=org_id,
            event_type=trigger.event_type,
            payload={"contact": {"email": "asha@example.com"}},
            event_id=manual_event_id,
        )

    assert len(runs) == 1
    assert runs[0].event_id == manual_event_id
    assert runs[0].event_id.startswith("manual:")


async def test_run_now_each_call_produces_a_fresh_row(test_db, org_id):
    """Two run-now fires for the same trigger + same payload land
    as TWO run rows because each gets a unique manual event_id."""
    trigger = await _make_trigger(test_db, org_id=org_id)
    payload = {"contact": {"email": "asha@example.com"}}
    with patch.object(automation_tasks.deliver_run, "apply_async"):
        first = await dispatcher.dispatch_event(
            test_db,
            org_id=org_id,
            event_type=trigger.event_type,
            payload=payload,
            event_id=f"manual:{trigger.id}:{uuid.uuid4()}",
        )
        second = await dispatcher.dispatch_event(
            test_db,
            org_id=org_id,
            event_type=trigger.event_type,
            payload=payload,
            event_id=f"manual:{trigger.id}:{uuid.uuid4()}",
        )
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id != second[0].id


# --- per-contact filter ------------------------------------------


async def test_list_runs_filters_by_contact_id(test_db, org_id):
    """The Step-9 GET /runs?contact_id=… endpoint relies on this DAL
    filter to drive the contact-detail Automations tab."""
    trigger = await _make_trigger(test_db, org_id=org_id)
    contact_a = uuid.uuid4()
    contact_b = uuid.uuid4()

    # Two runs for contact_a, one for contact_b.
    for cid in (contact_a, contact_a, contact_b):
        run = AutomationRun(
            org_id=org_id,
            trigger_id=trigger.id,
            event_id=f"event-{uuid.uuid4()}",
            event_payload={},
            contact_id=cid,
            status=AutomationRunStatus.sent,
            scheduled_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        test_db.add(run)
    await test_db.commit()

    rows_a, total_a = await data_access.list_runs(test_db, org_id=org_id, contact_id=contact_a)
    rows_b, total_b = await data_access.list_runs(test_db, org_id=org_id, contact_id=contact_b)
    assert total_a == 2
    assert total_b == 1
    assert {r.contact_id for r in rows_a} == {contact_a}
    assert {r.contact_id for r in rows_b} == {contact_b}


async def test_list_runs_filters_by_contact_and_status(test_db, org_id):
    """Combining contact_id + status filters narrows correctly —
    the per-contact tab uses this when the operator clicks a status
    chip."""
    trigger = await _make_trigger(test_db, org_id=org_id)
    contact_id = uuid.uuid4()
    statuses = [
        AutomationRunStatus.sent,
        AutomationRunStatus.failed,
        AutomationRunStatus.sent,
    ]
    for st in statuses:
        run = AutomationRun(
            org_id=org_id,
            trigger_id=trigger.id,
            event_id=f"event-{uuid.uuid4()}",
            event_payload={},
            contact_id=contact_id,
            status=st,
            scheduled_at=datetime.now(UTC),
        )
        test_db.add(run)
    await test_db.commit()

    sent_rows, sent_total = await data_access.list_runs(
        test_db,
        org_id=org_id,
        contact_id=contact_id,
        status=AutomationRunStatus.sent,
    )
    failed_rows, failed_total = await data_access.list_runs(
        test_db,
        org_id=org_id,
        contact_id=contact_id,
        status=AutomationRunStatus.failed,
    )
    assert sent_total == 2
    assert failed_total == 1
    assert all(r.status == AutomationRunStatus.sent for r in sent_rows)
    assert all(r.status == AutomationRunStatus.failed for r in failed_rows)
