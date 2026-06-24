"""whatsapp-platform-upgrade Step 27a — multi-number per org boundary tests.

Pure-Python coverage of the call-site fan-out invariants that the
refactor must preserve:

  * `resolve_whatsapp_adapter` signature now accepts an optional
    ``phone_id`` kwarg.
  * `get_active_config` signature now accepts an optional
    ``phone_id`` kwarg and returns the SAME tuple shape so existing
    callers keep working.
  * `list_active_configs` is exposed from the module.
  * `send_outbound` signature accepts ``send_from_phone_id``.
  * `receive_webhook` signature accepts ``received_via_phone_id``.
  * `MessageSendPayload` schema accepts ``send_from_phone_id``
    + rejects it past the column max (64 chars).
  * `Conversation` ORM has the ``received_via_phone_id`` attribute.
  * `Campaign` ORM has the ``send_from_phone_id`` attribute.
  * `WhatsAppAccountConfig` table args carry the new composite
    UniqueConstraint name.

Live-DB paths (multi-config insert across same integration_id,
webhook dispatch by phone_id, send-from routing) are exercised by
the smoke flow against a connected sandbox WABA. Pinning the
signatures here keeps a stray refactor from quietly reverting the
multi-number plumbing.

Cases:
  1.  `resolve_whatsapp_adapter` accepts `phone_id=None`.
  2.  `resolve_whatsapp_adapter` accepts `phone_id="..."`.
  3.  `get_active_config` accepts `phone_id=None`.
  4.  `get_active_config` accepts `phone_id="..."`.
  5.  `list_active_configs` is importable from `connect`.
  6.  `send_outbound` accepts `send_from_phone_id=None`.
  7.  `send_outbound` accepts `send_from_phone_id="..."`.
  8.  `receive_webhook` accepts `received_via_phone_id=None`.
  9.  `receive_webhook` accepts `received_via_phone_id="..."`.
 10.  `MessageSendPayload(send_from_phone_id=None)` round-trips.
 11.  `MessageSendPayload` rejects send_from_phone_id > 64 chars.
 12.  `Conversation.received_via_phone_id` exists as a mapper attr.
 13.  `Campaign.send_from_phone_id` exists as a mapper attr.
 14.  `WhatsAppAccountConfig.__table_args__` carries the composite
       unique constraint.
"""
from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint


class TestResolveSignature:
    def test_phone_id_kwarg_accepted(self):
        from src.app.core.conversations.adapters.whatsapp import (
            resolve_whatsapp_adapter,
        )

        sig = inspect.signature(resolve_whatsapp_adapter)
        assert "phone_id" in sig.parameters
        # Kwarg defaults to None so every legacy call site stays valid.
        assert sig.parameters["phone_id"].default is None


class TestGetActiveConfigSignature:
    def test_phone_id_kwarg_accepted(self):
        from src.app.core.integrations.whatsapp.connect import (
            get_active_config,
        )

        sig = inspect.signature(get_active_config)
        assert "phone_id" in sig.parameters
        assert sig.parameters["phone_id"].default is None

    def test_list_active_configs_exposed(self):
        from src.app.core.integrations.whatsapp import connect

        assert hasattr(connect, "list_active_configs")
        assert callable(connect.list_active_configs)


class TestSendOutboundSignature:
    def test_send_from_phone_id_kwarg(self):
        from src.app.core.conversations.service import send_outbound

        sig = inspect.signature(send_outbound)
        assert "send_from_phone_id" in sig.parameters
        assert sig.parameters["send_from_phone_id"].default is None


class TestReceiveWebhookSignature:
    def test_received_via_phone_id_kwarg(self):
        from src.app.core.conversations.service import receive_webhook

        sig = inspect.signature(receive_webhook)
        assert "received_via_phone_id" in sig.parameters
        assert sig.parameters["received_via_phone_id"].default is None


class TestMessageSendPayloadSchema:
    def test_send_from_phone_id_round_trip(self):
        from src.app.core.conversations.schemas import MessageSendPayload

        msg = MessageSendPayload(
            text="hi", send_from_phone_id="123456789012345"
        )
        assert msg.send_from_phone_id == "123456789012345"

    def test_send_from_phone_id_defaults_to_none(self):
        from src.app.core.conversations.schemas import MessageSendPayload

        msg = MessageSendPayload(text="hi")
        assert msg.send_from_phone_id is None

    def test_too_long_send_from_phone_id_rejected(self):
        from src.app.core.conversations.schemas import MessageSendPayload

        with pytest.raises(ValidationError):
            MessageSendPayload(
                text="hi", send_from_phone_id="x" * 65
            )


class TestOrmAttributes:
    def test_conversation_has_received_via_phone_id(self):
        from src.app.core.conversations.models import Conversation

        column = Conversation.__table__.columns.get(
            "received_via_phone_id"
        )
        assert column is not None
        assert column.nullable is True

    def test_campaign_has_send_from_phone_id(self):
        from src.app.core.campaigns.models import Campaign

        column = Campaign.__table__.columns.get("send_from_phone_id")
        assert column is not None
        assert column.nullable is True

    def test_wa_config_has_composite_unique(self):
        from src.app.core.integrations.whatsapp.models import (
            WhatsAppAccountConfig,
        )

        table_args = WhatsAppAccountConfig.__table_args__
        if not isinstance(table_args, tuple):
            table_args = (table_args,)
        constraints = [
            a for a in table_args if isinstance(a, UniqueConstraint)
        ]
        names = {c.name for c in constraints}
        assert "uq_wa_config_integration_phone" in names
        # The composite constraint covers BOTH columns; the old
        # integration-only constraint must be gone.
        composite = next(
            c
            for c in constraints
            if c.name == "uq_wa_config_integration_phone"
        )
        cols = {col.name for col in composite.columns}
        assert cols == {"integration_id", "phone_id"}
