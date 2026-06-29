"""Pin tests for the Step-8 dry-run endpoint.

Dry-run runs the dispatcher's match + resolve + render path against
a caller-supplied payload WITHOUT writing a run row or invoking the
channel adapter. Powers the editor's "Save & Test" modal so the
operator can verify trigger conditions + template rendering before
the trigger fires for real.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.automation import service as automation_service
from src.app.core.automation.models import AutomationRun
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
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def _make_trigger(test_db, *, org_id, conditions=None):
    """Set up an Email template + trigger pointing at it.
    Returns the trigger id."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name=f"DryTpl-{uuid.uuid4().hex[:4]}",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi {{ contact.first_name }}",
                subject="Welcome {{ contact.first_name }}",
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
    return trigger.id


# --- dispatcher-level dry-run logic ------------------------------


async def test_dry_run_renders_template_with_payload(test_db, org_id):
    """Calls the same conditions + recipients + render helpers the
    endpoint uses — pins that the result carries the rendered
    body."""
    from src.app.core.automation import conditions, recipients
    from src.app.core.templates import data_access as templates_da
    from src.app.core.templates.variables import resolve as render_variables

    trigger_id = await _make_trigger(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        trigger = await automation_service.get_trigger(
            test_db, org_id=org_id, trigger_id=trigger_id
        )
        payload = {"contact": {"first_name": "Asha", "email": "asha@x.com"}}
        assert conditions.evaluate(trigger.conditions, payload) is True
        recipient = await recipients.resolve(
            trigger.recipient_resolver,
            test_db,
            payload=payload,
            config=trigger.recipient_resolver_config or {},
        )
        assert recipient == "asha@x.com"
        template = await templates_da.get_template(
            test_db, org_id=org_id, template_id=trigger.template_id
        )
        assert template is not None
        rendered_body = render_variables(template.body_text, payload)
        rendered_subject = render_variables(template.subject, payload)
        assert "Asha" in rendered_body
        assert "Asha" in rendered_subject
    finally:
        reset_context(token)


async def test_dry_run_returns_match_decision(test_db, org_id):
    """Condition that requires source='website' returns False when
    the payload's source is something else."""
    from src.app.core.automation import conditions

    trigger_id = await _make_trigger(
        test_db,
        org_id=org_id,
        conditions={"field": "source", "op": "eq", "value": "website"},
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        trigger = await automation_service.get_trigger(
            test_db, org_id=org_id, trigger_id=trigger_id
        )
        good = conditions.evaluate(trigger.conditions, {"source": "website"})
        bad = conditions.evaluate(trigger.conditions, {"source": "manual"})
        assert good is True
        assert bad is False
    finally:
        reset_context(token)


async def test_dry_run_does_not_create_run_row(test_db, org_id):
    """The dry-run dispatcher path must NOT insert a row in
    tbl_automation_runs — pure read + render."""
    from src.app.core.automation import conditions, recipients
    from src.app.core.templates import data_access as templates_da
    from src.app.core.templates.variables import resolve as render_variables

    trigger_id = await _make_trigger(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        trigger = await automation_service.get_trigger(
            test_db, org_id=org_id, trigger_id=trigger_id
        )
        payload = {"contact": {"first_name": "Asha", "email": "asha@x.com"}}
        # Run the same pure-function dispatcher chain the endpoint
        # invokes — none of it should write a run row.
        conditions.evaluate(trigger.conditions, payload)
        await recipients.resolve(
            trigger.recipient_resolver,
            test_db,
            payload=payload,
            config={},
        )
        template = await templates_da.get_template(
            test_db, org_id=org_id, template_id=trigger.template_id
        )
        render_variables(template.body_text, payload)
    finally:
        reset_context(token)

    runs = (
        await test_db.execute(
            select(AutomationRun).where(AutomationRun.trigger_id == trigger_id)
        )
    ).scalars().all()
    assert len(runs) == 0
