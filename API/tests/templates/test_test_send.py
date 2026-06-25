"""Tests for the per-channel test-send orchestrator.

Covers the validator (email vs phone shape), the channel dispatch
matrix (email + WhatsApp implemented, SMS / FB / IG / push raise
``TestSendNotSupported``), and the audit-row write.

Adapter calls are stubbed at the module boundary so we don't need
a Meta token or a live SMTP server.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.conversations.adapters import ChannelMessageRef
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates import test_send as templates_test_send
from src.app.core.templates.exceptions import (
    InvalidRecipient,
    TestSendNotSupported,
)
from src.app.core.templates.models import (
    MessageTemplateTestSend,
    TemplateCategory,
)
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    """Seed one org row so template inserts don't violate the FK."""
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


async def _make_email_template(test_db, *, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="Welcome",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi {{ contact.first_name }}",
                subject="Welcome to {{ org.name }}",
            ),
        )
    finally:
        reset_context(token)


async def _make_template(test_db, *, org_id, channel):
    """Create a template with channel-correct shape (subject only for email)."""
    payload_kwargs: dict[str, Any] = {
        "name": f"T-{channel.value}",
        "channel": channel,
        "category": TemplateCategory.marketing,
        "body_text": "Hi {{ contact.first_name }}",
    }
    if channel == ConversationChannel.email:
        payload_kwargs["subject"] = "Hello"
    token = set_context(RequestContext(org_id=org_id))
    try:
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(**payload_kwargs),
        )
    finally:
        reset_context(token)


# --- recipient validator ----------------------------------------------


def test_email_recipient_shape():
    out = templates_test_send._validate_recipient(
        ConversationChannel.email, "  asha@example.com "
    )
    assert out == "asha@example.com"


def test_email_recipient_rejected():
    with pytest.raises(InvalidRecipient):
        templates_test_send._validate_recipient(
            ConversationChannel.email, "not-an-email"
        )


def test_phone_recipient_strips_plus_and_spaces():
    out = templates_test_send._validate_recipient(
        ConversationChannel.whatsapp, "+91 98765 43210"
    )
    assert out == "919876543210"


def test_phone_too_short_rejected():
    with pytest.raises(InvalidRecipient):
        templates_test_send._validate_recipient(
            ConversationChannel.whatsapp, "1234"
        )


def test_empty_recipient_rejected():
    with pytest.raises(InvalidRecipient):
        templates_test_send._validate_recipient(
            ConversationChannel.email, "   "
        )


# --- dispatch matrix --------------------------------------------------


async def test_dispatch_email_writes_audit_row(test_db, org_id):
    template = await _make_email_template(test_db, org_id=org_id)

    with patch.object(
        templates_test_send, "_dispatch_email", new=AsyncMock(return_value=None)
    ) as mock:
        out = await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="owner@example.com",
            user_id=None,
            sample_context={"org": {"name": "Acme"}},
        )

    assert isinstance(out, MessageTemplateTestSend)
    assert out.sent_to == "owner@example.com"
    assert out.version == template.current_version
    assert out.channel == ConversationChannel.email
    # Adapter received the rendered subject + body.
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["recipient"] == "owner@example.com"
    assert call_kwargs["subject"] == "Welcome to Acme"
    assert "Hi Sample" in call_kwargs["body"]

    # Audit row persists.
    row = (
        await test_db.execute(
            select(MessageTemplateTestSend).where(
                MessageTemplateTestSend.template_id == template.id
            )
        )
    ).scalar_one()
    assert row.id == out.id


async def test_dispatch_whatsapp_calls_adapter(test_db, org_id):
    template = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.whatsapp
    )

    fake_ref = ChannelMessageRef(channel_message_id="wamid.TEST123")
    with patch.object(
        templates_test_send,
        "_dispatch_whatsapp",
        new=AsyncMock(return_value=fake_ref.channel_message_id),
    ) as mock:
        out = await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="+91 98765 43210",
            user_id=None,
        )

    assert out.channel == ConversationChannel.whatsapp
    assert out.channel_message_id == "wamid.TEST123"
    assert out.sent_to == "919876543210"  # normalised
    assert mock.call_args.kwargs["recipient"] == "919876543210"


async def test_dispatch_sms_returns_not_supported(test_db, org_id):
    template = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.sms
    )
    with pytest.raises(TestSendNotSupported) as info:
        await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="919876543210",
            user_id=None,
        )
    assert info.value.channel == "sms"


async def test_dispatch_facebook_returns_not_supported(test_db, org_id):
    template = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.facebook
    )
    with pytest.raises(TestSendNotSupported):
        await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="page-handle",
            user_id=None,
        )


async def test_dispatch_email_with_invalid_recipient_raises(test_db, org_id):
    template = await _make_email_template(test_db, org_id=org_id)
    with pytest.raises(InvalidRecipient):
        await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="not-an-email",
            user_id=None,
        )


async def test_test_send_works_on_draft_template(test_db, org_id):
    """No requirement that the template be approved/published — test
    send is the operator's way to vet a fresh draft."""
    template = await _make_email_template(test_db, org_id=org_id)
    # internal_status defaults to 'draft' — confirm.
    assert template.internal_status.value == "draft"

    with patch.object(
        templates_test_send, "_dispatch_email", new=AsyncMock(return_value=None)
    ):
        out = await templates_test_send.dispatch_test_send(
            test_db,
            org_id=org_id,
            template_id=template.id,
            recipient="self@example.com",
            user_id=None,
        )
    assert out is not None
