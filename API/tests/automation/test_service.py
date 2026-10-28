"""Pin tests for the Step-2 automation service.

CRUD happy paths + duplicate-name rejection + template/channel
consistency + matcher correctness (only enabled triggers; only
conditions-matching triggers).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.automation import service as automation_service
from src.app.core.automation.exceptions import (
    DuplicateTriggerName,
    MissingTemplateForChannel,
    TriggerNotFound,
)
from src.app.core.automation.schemas import TriggerCreate, TriggerUpdate
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import TemplateCategory
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


# --- fixtures ----------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def _make_template(test_db, *, org_id, channel: ConversationChannel):
    token = set_context(RequestContext(org_id=org_id))
    try:
        payload_kwargs = {
            "name": f"Tpl-{channel.value}-{uuid.uuid4().hex[:4]}",
            "channel": channel,
            "category": TemplateCategory.transactional,
            "body_text": "Hi {{ contact.first_name }}",
        }
        if channel == ConversationChannel.email:
            payload_kwargs["subject"] = "Hello"
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(**payload_kwargs),
        )
    finally:
        reset_context(token)


# --- create ------------------------------------------------------


async def test_create_trigger_writes_row(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    trigger = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Welcome email",
            event_type="user.signed_up",
            channel=ConversationChannel.email,
            template_id=template.id,
        ),
    )
    assert trigger.id is not None
    assert trigger.enabled is True
    assert trigger.delay_seconds == 0
    assert trigger.event_type == "user.signed_up"


async def test_create_trigger_rejects_duplicate_name(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Welcome email",
            event_type="user.signed_up",
            channel=ConversationChannel.email,
            template_id=template.id,
        ),
    )
    with pytest.raises(DuplicateTriggerName):
        await automation_service.create_trigger(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TriggerCreate(
                name="welcome email",  # case-insensitive collision
                event_type="lead.created",
                channel=ConversationChannel.email,
                template_id=template.id,
            ),
        )


async def test_create_trigger_rejects_template_channel_mismatch(test_db, org_id):
    email_template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    with pytest.raises(MissingTemplateForChannel) as info:
        await automation_service.create_trigger(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TriggerCreate(
                name="WA welcome",
                event_type="user.signed_up",
                channel=ConversationChannel.whatsapp,
                template_id=email_template.id,
            ),
        )
    assert info.value.template_channel == "email"
    assert info.value.trigger_channel == "whatsapp"


async def test_create_trigger_persists_conditions_and_resolver(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    trigger = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Hot lead",
            event_type="lead.score_threshold",
            channel=ConversationChannel.email,
            template_id=template.id,
            conditions={"field": "lead.score", "op": "gte", "value": 75},
            recipient_resolver="custom",
            recipient_resolver_config={"path": "lead.owner_email"},
        ),
    )
    assert trigger.conditions == {
        "field": "lead.score",
        "op": "gte",
        "value": 75,
    }
    assert trigger.recipient_resolver == "custom"
    assert trigger.recipient_resolver_config == {"path": "lead.owner_email"}


# --- enable / disable / update / delete -------------------------


async def test_enable_disable_idempotent(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    trigger = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Toggleable",
            event_type="user.signed_up",
            channel=ConversationChannel.email,
            template_id=template.id,
            enabled=True,
        ),
    )
    # disable twice — no-op the second time
    t = await automation_service.disable_trigger(
        test_db, org_id=org_id, user_id=None, trigger_id=trigger.id
    )
    assert t.enabled is False
    t = await automation_service.disable_trigger(
        test_db, org_id=org_id, user_id=None, trigger_id=trigger.id
    )
    assert t.enabled is False
    # enable
    t = await automation_service.enable_trigger(
        test_db, org_id=org_id, user_id=None, trigger_id=trigger.id
    )
    assert t.enabled is True


async def test_update_trigger_patches_fields(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    trigger = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Welcome",
            event_type="user.signed_up",
            channel=ConversationChannel.email,
            template_id=template.id,
        ),
    )
    updated = await automation_service.update_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        trigger_id=trigger.id,
        payload=TriggerUpdate(delay_seconds=300, name="Welcome v2"),
    )
    assert updated.delay_seconds == 300
    assert updated.name == "Welcome v2"
    # Unchanged fields preserved.
    assert updated.event_type == "user.signed_up"


async def test_delete_trigger_removes_row(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    trigger = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Throwaway",
            event_type="user.signed_up",
            channel=ConversationChannel.email,
            template_id=template.id,
        ),
    )
    await automation_service.delete_trigger(test_db, org_id=org_id, trigger_id=trigger.id)
    with pytest.raises(TriggerNotFound):
        await automation_service.get_trigger(test_db, org_id=org_id, trigger_id=trigger.id)


# --- matcher ----------------------------------------------------


async def test_match_triggers_returns_only_enabled(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    enabled = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Enabled",
            event_type="lead.created",
            channel=ConversationChannel.email,
            template_id=template.id,
            enabled=True,
        ),
    )
    await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Disabled",
            event_type="lead.created",
            channel=ConversationChannel.email,
            template_id=template.id,
            enabled=False,
        ),
    )
    matches = await automation_service.match_triggers(
        test_db,
        org_id=org_id,
        event_type="lead.created",
        payload={},
    )
    assert [t.id for t in matches] == [enabled.id]


async def test_match_triggers_filters_by_conditions(test_db, org_id):
    template = await _make_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    hot = await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Hot",
            event_type="lead.created",
            channel=ConversationChannel.email,
            template_id=template.id,
            conditions={"field": "lead.score", "op": "gte", "value": 75},
        ),
    )
    await automation_service.create_trigger(
        test_db,
        org_id=org_id,
        user_id=None,
        payload=TriggerCreate(
            name="Cold",
            event_type="lead.created",
            channel=ConversationChannel.email,
            template_id=template.id,
            conditions={"field": "lead.score", "op": "lt", "value": 25},
        ),
    )
    matches = await automation_service.match_triggers(
        test_db,
        org_id=org_id,
        event_type="lead.created",
        payload={"lead": {"score": 80}},
    )
    assert [t.id for t in matches] == [hot.id]


async def test_get_trigger_not_found_raises(test_db, org_id):
    with pytest.raises(TriggerNotFound):
        await automation_service.get_trigger(test_db, org_id=org_id, trigger_id=uuid.uuid4())
