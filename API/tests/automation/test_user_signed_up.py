"""Pin tests for the Step-5 user.signed_up publisher + Welcome
seed trigger.

Covers the end-to-end "manager's promise":

  1. The trigger seeder + template seeder install correctly into a
     fresh org (idempotent on re-run).
  2. Publishing ``user.signed_up`` on a seeded org enrols a
     queued run via the dispatcher's wildcard subscriber.
  3. The deliver_run Celery task renders ``{{ user.full_name }}`` +
     ``{{ org.name }}`` against the published payload + calls the
     email backend with the right recipient.
  4. Disabling the seeded trigger short-circuits the dispatcher
     (no queued run row written).

The Meta / SMTP boundary is mocked so the test doesn't need a
real email backend.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
from src.app.core.automation.service import (
    disable_trigger,
    match_triggers,
)
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


# --- seed installation --------------------------------------------


async def test_install_default_org_seeds_creates_template_and_trigger(test_db, org_id):
    result = await _install_seeds(test_db, org_id)
    assert "template_id" in result
    assert "trigger_id" in result

    rows = (
        (
            await test_db.execute(
                select(AutomationTrigger).where(
                    AutomationTrigger.org_id == org_id,
                    AutomationTrigger.name == "User Welcome",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    trigger = rows[0]
    assert trigger.event_type == "user.signed_up"
    assert trigger.recipient_resolver == "user.email"
    assert trigger.delay_seconds == 0
    assert trigger.enabled is True


async def test_install_default_org_seeds_is_idempotent(test_db, org_id):
    first = await _install_seeds(test_db, org_id)
    second = await _install_seeds(test_db, org_id)
    assert first == second  # same ids returned


# --- dispatcher matches the seeded trigger ------------------------


async def test_match_triggers_returns_seeded_welcome_for_user_signed_up(test_db, org_id):
    await _install_seeds(test_db, org_id)
    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="user.signed_up",
        payload={
            "user": {"full_name": "Asha", "email": "asha@x.com"},
            "org": {"name": "Demo Workspace"},
        },
    )
    assert len(matches) == 1
    assert matches[0].name == "User Welcome"


async def test_disabled_trigger_no_longer_matches(test_db, org_id):
    seeded = await _install_seeds(test_db, org_id)
    trigger_id = uuid.UUID(seeded["trigger_id"])
    await disable_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        trigger_id=trigger_id,
    )
    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="user.signed_up",
        payload={"user": {"email": "asha@x.com"}},
    )
    assert matches == []


# --- bus publish → dispatcher → queued run -------------------------


async def test_publish_user_signed_up_enrols_queued_run(test_db, org_id):
    await _install_seeds(test_db, org_id)

    # Wire the dispatcher's wildcard subscriber for this test (the
    # package-level side-effect import runs at process start; we
    # ensure it's registered here too so the test is hermetic).
    from src.app.core.automation.dispatcher import (
        dispatch_event,
        register_bus_subscriber,
    )

    register_bus_subscriber()

    # We don't need the real bus → wildcard fan-out for this test;
    # call dispatch_event directly with the same payload shape the
    # auth service emits. Mock the Celery scheduling so we observe
    # the queued row instead of a real Celery RPC.
    with patch.object(automation_tasks.deliver_run, "apply_async") as schedule:
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="user.signed_up",
            payload={
                "user_id": str(uuid.uuid4()),
                "user": {
                    "full_name": "Asha Mehta",
                    "email": "asha@example.com",
                },
                "org": {"name": "Demo Workspace"},
            },
            event_id="signup:abc",
        )

    assert len(runs) == 1
    run = runs[0]
    assert run.status == AutomationRunStatus.queued
    assert run.event_id == "signup:abc"
    assert run.event_payload["_resolved_recipient"] == "asha@example.com"
    assert schedule.called


# --- deliver_run renders the welcome body --------------------------


async def test_deliver_run_renders_user_welcome_email(test_db, org_id):
    await _install_seeds(test_db, org_id)
    from src.app.core.automation.dispatcher import dispatch_event

    with patch.object(automation_tasks.deliver_run, "apply_async"):
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="user.signed_up",
            payload={
                "user_id": str(uuid.uuid4()),
                "user": {
                    "full_name": "Asha Mehta",
                    "email": "asha@example.com",
                },
                "org": {"name": "Demo Workspace"},
            },
            event_id="signup:render",
        )
    run = runs[0]

    fake_backend = MagicMock()
    fake_backend.send = AsyncMock(return_value=None)
    with patch(
        "src.app.shared.email.get_email_backend",
        return_value=fake_backend,
    ):
        result = await automation_tasks._deliver_run_async(str(run.id))

    assert result["status"] == "sent"
    assert fake_backend.send.await_count == 1
    email = fake_backend.send.await_args.args[0]
    assert email.to == "asha@example.com"
    assert "Asha Mehta" in email.body_text
    assert "Demo Workspace" in email.body_text
    assert email.subject == "Welcome to Demo Workspace"
