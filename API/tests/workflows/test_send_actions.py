"""Pin tests for the Step-7 Send action handlers.

Covers each handler's happy + sad paths. Channel adapters are
mocked at the conversations registry boundary so no real
transports fire. The email backend is exercised via the in-process
``LogEmailBackend`` (the default when ``EMAIL_ENABLED=false`` in
the test config).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import TemplateCategory
from src.app.core.templates.schemas import TemplateCreate
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
)
from src.app.core.workflows.actions import (
    resolve as resolve_action,
)
from src.app.core.workflows.actions import send as send_module  # noqa: F401
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None
    id: uuid.UUID = uuid.uuid4()


@dataclass
class _FakeStepRun:
    id: uuid.UUID


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


@pytest.fixture(autouse=True)
def _reset_action_registry():
    """Wipe + restore registrations between cases so the engine's
    built-ins + Step-7 send handlers always resolve."""
    _clear_registry_for_tests()
    _register_builtins()
    # Re-fire the send.py register() since _clear wiped it.
    send_module.register()
    # flow_control.py too.
    from src.app.core.workflows.actions import flow_control as fc

    fc.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()


async def _seed_template(test_db, *, org_id, channel: ConversationChannel):
    token = set_context(RequestContext(org_id=org_id))
    try:
        tpl = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name=f"WfSend-{uuid.uuid4().hex[:4]}",
                channel=channel,
                category=TemplateCategory.transactional,
                body_text="Hi {{ contact.full_name }}",
                subject="Hello" if channel == ConversationChannel.email else None,
            ),
        )
    finally:
        reset_context(token)
    return tpl


def _send_email_node(template_id: uuid.UUID) -> dict:
    return {
        "id": "s1",
        "type": "send.email",
        "config": {
            "template_id": str(template_id),
            "recipient": "contact.email",
        },
    }


# ---------------------------------------------------------------------------
# send.email — happy + skip
# ---------------------------------------------------------------------------


async def test_send_email_happy_renders_and_calls_backend(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.email)

    handler = resolve_action("send.email")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {
            "email": "asha@example.com",
            "full_name": "Asha Mehta",
        },
        "trigger_payload": {},
        "run_state": {},
    }
    node = _send_email_node(template.id)

    sent: dict = {}

    class _CaptureBackend:
        async def send(self, email):
            sent["to"] = email.to
            sent["subject"] = email.subject
            sent["body"] = email.body_text

    with patch(
        "src.app.shared.email.get_email_backend",
        return_value=_CaptureBackend(),
    ):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(id=uuid.uuid4()),
            node=node,
            context=context,
        )

    assert result.skip_reason is None
    assert sent["to"] == "asha@example.com"
    # Lenient render — `{{ contact.full_name }}` resolved.
    assert "Asha Mehta" in sent["body"]
    assert result.output["rendered_body"] == sent["body"]


async def test_send_email_skips_when_recipient_missing(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    handler = resolve_action("send.email")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {"contact": {}, "trigger_payload": {}, "run_state": {}}
    node = _send_email_node(template.id)

    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(id=uuid.uuid4()),
        node=node,
        context=context,
    )

    assert result.skip_reason == "recipient_not_found"


async def test_send_email_skips_when_template_missing(test_db, org_id):
    handler = resolve_action("send.email")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"email": "asha@example.com"},
        "trigger_payload": {},
        "run_state": {},
    }
    # Reference a template that doesn't exist for this org.
    node = {
        "id": "s1",
        "type": "send.email",
        "config": {
            "template_id": str(uuid.uuid4()),
            "recipient": "contact.email",
        },
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(id=uuid.uuid4()),
        node=node,
        context=context,
    )
    assert result.skip_reason == "template_missing"


# ---------------------------------------------------------------------------
# send.whatsapp — happy + adapter-not-configured
# ---------------------------------------------------------------------------


async def test_send_whatsapp_happy_via_mocked_adapter(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.whatsapp)
    handler = resolve_action("send.whatsapp")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {
            "phone": "+919876543210",
            "full_name": "Asha Mehta",
        },
        "trigger_payload": {},
        "run_state": {},
    }
    node = {
        "id": "wa1",
        "type": "send.whatsapp",
        "config": {
            "template_id": str(template.id),
            "recipient": "contact.phone",
        },
    }

    class _FakeRef:
        channel_message_id = "wamid.123abc"

    fake_adapter = AsyncMock()
    fake_adapter.send = AsyncMock(return_value=_FakeRef())

    with patch(
        "src.app.core.conversations.registry.resolve",
        return_value=fake_adapter,
    ):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(id=uuid.uuid4()),
            node=node,
            context=context,
        )

    assert result.skip_reason is None
    assert result.output["channel_message_id"] == "wamid.123abc"
    fake_adapter.send.assert_awaited_once()
    call = fake_adapter.send.await_args
    assert call.kwargs["external_id"] == "+919876543210"
    assert "Asha Mehta" in call.kwargs["text"]


async def test_send_whatsapp_channel_not_registered_skips(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.whatsapp)
    handler = resolve_action("send.whatsapp")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"phone": "+919876543210", "full_name": "Asha"},
        "trigger_payload": {},
        "run_state": {},
    }
    node = {
        "id": "wa1",
        "type": "send.whatsapp",
        "config": {
            "template_id": str(template.id),
            "recipient": "contact.phone",
        },
    }

    from src.app.core.conversations.registry import ChannelNotRegistered

    def _raise(_channel):
        raise ChannelNotRegistered("whatsapp not registered in test env")

    with patch("src.app.core.conversations.registry.resolve", side_effect=_raise):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(id=uuid.uuid4()),
            node=node,
            context=context,
        )

    assert result.skip_reason == "channel_error"
    assert "not registered" in result.output["error"]


# ---------------------------------------------------------------------------
# send.slack — happy + bad webhook URL
# ---------------------------------------------------------------------------


async def test_send_slack_happy(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    handler = resolve_action("send.slack")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"full_name": "Asha"},
        "trigger_payload": {},
        "run_state": {},
    }
    node = {
        "id": "sl1",
        "type": "send.slack",
        "config": {
            "template_id": str(template.id),
            "webhook_url": "https://hooks.slack.com/services/T/B/X",
        },
    }

    fake_post = AsyncMock()
    with patch("src.app.core.integrations.slack.post_message", new=fake_post):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(id=uuid.uuid4()),
            node=node,
            context=context,
        )

    assert result.skip_reason is None
    fake_post.assert_awaited_once()
    call_args = fake_post.await_args
    assert call_args.args[0] == "https://hooks.slack.com/services/T/B/X"


async def test_send_slack_missing_webhook_skips(test_db, org_id):
    template = await _seed_template(test_db, org_id=org_id, channel=ConversationChannel.email)
    handler = resolve_action("send.slack")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {
        "id": "sl1",
        "type": "send.slack",
        "config": {"template_id": str(template.id)},  # no webhook_url
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(id=uuid.uuid4()),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "slack_webhook_missing"


# ---------------------------------------------------------------------------
# send.sms / send.facebook / send.instagram / send.push — consistent skip
# when no adapter is registered (the default in test env).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type", ["send.sms", "send.facebook", "send.instagram", "send.push"]
)
async def test_stub_channels_skip_when_adapter_missing(test_db, org_id, action_type):
    """The four stub channels share a dispatch shape — without a
    registered adapter the handler returns
    ``ActionResult(skip_reason='channel_error')`` with the
    adapter-name-specific reason inside output['skip_reason']."""
    # SMS template uses SMS channel; others reuse email-style
    # template body for simplicity.
    channel_map = {
        "send.sms": ConversationChannel.sms,
        "send.facebook": ConversationChannel.facebook,
        "send.instagram": ConversationChannel.instagram,
        "send.push": ConversationChannel.push,
    }
    template = await _seed_template(test_db, org_id=org_id, channel=channel_map[action_type])
    handler = resolve_action(action_type)
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"phone": "+919876543210", "email": "x@y.com"},
        "trigger_payload": {},
        "run_state": {},
    }
    node = {
        "id": "n1",
        "type": action_type,
        "config": {
            "template_id": str(template.id),
            "recipient": ("contact.email" if action_type == "send.push" else "contact.phone"),
        },
    }

    from src.app.core.conversations.registry import ChannelNotRegistered

    def _raise(_channel):
        raise ChannelNotRegistered(f"{action_type} not registered")

    with patch("src.app.core.conversations.registry.resolve", side_effect=_raise):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(id=uuid.uuid4()),
            node=node,
            context=context,
        )

    assert result.skip_reason == "channel_error"
    assert action_type.split(".", 1)[1] in result.output["skip_reason"]
