"""Tests for the omnichannel AI dispatch
(``tasks/ai-assistants-omnichannel`` Step 5).

Pure-function tests for the handover keyword matcher + shallow smoke
tests for the dispatch shim. Deep integration (LLM invocation +
adapter send) is covered by the existing WhatsApp AI handler test
suite; this file only asserts the new gates land in the right order.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


# --- Handover keyword matcher (pure function) -------------------------


def test_handover_matches_default_keyword() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Please talk to a human, this bot is useless")
    assert matches("HUMAN PLEASE")  # case-insensitive
    assert matches("Can I speak to a person?")


def test_handover_no_match_on_regular_text() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Hi, do you have leather sofas?") is False
    assert matches("What's your return policy") is False


def test_handover_matches_operator_extra_keyword() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("नमस्ते, मुझे इंसान से बात करनी है", extra_keywords=["इंसान से बात"]) is True


def test_handover_ignores_blank_extras() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Hi there", extra_keywords=["", "  "]) is False


def test_handover_none_or_empty_returns_false() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches(None) is False
    assert matches("") is False


# --- Dispatch shim (gate order) ---------------------------------------


class _FakeConversation(SimpleNamespace):
    """Minimal stand-in for the ``Conversation`` ORM row so we can
    exercise the dispatch's gates without a real DB session. The
    dispatch treats it as an attribute bag — ``ai_paused``,
    ``ai_handling``, ``id``, ``org_id``."""


@pytest.fixture
def fake_conv() -> _FakeConversation:
    return _FakeConversation(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        ai_paused=False,
        ai_handling=False,
    )


async def test_dispatch_skips_when_paused(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_conv.ai_paused = True
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with patch(
        "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
    ) as bound_mock:
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        # Paused short-circuits BEFORE the binding lookup.
        bound_mock.assert_not_called()


async def test_dispatch_auto_pauses_on_handover_keyword(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_session.commit = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.conversations.service.apply_auto_pause",
            new=AsyncMock(return_value=True),
        ) as pause_mock,
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="please talk to a human",
        )
        pause_mock.assert_awaited_once()
        # Handover fires BEFORE the binding lookup, and definitely
        # before the reply pipeline delegates.
        bound_mock.assert_not_called()


async def test_dispatch_delegates_when_bound_assistant_exists(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    fake_bound_assistant = SimpleNamespace(id=uuid.uuid4(), name="Test")

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_bound_assistant),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(return_value=None),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Do you have leather sofas?",
        )
        legacy_mock.assert_awaited_once()


async def test_dispatch_skips_when_no_bound_and_ai_handling_false(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        legacy_mock.assert_not_called()


async def test_dispatch_delegates_legacy_when_ai_handling_true(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_conv.ai_handling = True
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        legacy_mock.assert_awaited_once()


# --- Email dispatch (route_email_inbound + _run_ai_email_reply) ------


def _fake_email_envelope(
    *,
    body: str = "Do you have leather sofas in stock?",
    subject: str | None = "Sofa enquiry",
    sender: str = "customer@example.com",
    message_id: str | None = "<abc123@customer.example.com>",
    references: str | None = None,
):
    """Minimal InboundEmail envelope for the guardrail + threading."""
    from src.app.core.ai_assistants.email_guardrails import InboundEmail

    headers: dict[str, str] = {"From": sender}
    if subject is not None:
        headers["Subject"] = subject
    if message_id is not None:
        headers["Message-ID"] = message_id
    if references is not None:
        headers["References"] = references
    return InboundEmail(
        sender_email=sender,
        subject=subject,
        body_text=body,
        headers=headers,
    )


@pytest.fixture
def fake_email_conv() -> _FakeConversation:
    return _FakeConversation(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        ai_paused=False,
    )


async def test_email_route_flag_off_returns_none(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """When ``AI_EMAIL_INBOUND_ENABLED`` is False the dispatch must
    short-circuit BEFORE any DB lookup so orgs upgrading without a
    bound email assistant see zero behaviour change."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", False),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    bound_mock.assert_not_called()
    fake_session.refresh.assert_not_called()


async def test_email_route_paused_skips_reply(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """A human took over — flag is on, guardrail would pass, but AI
    stays silent."""
    from src.app.core.ai_assistants import dispatch

    fake_email_conv.ai_paused = True
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    # Pause gate fires BEFORE the binding lookup.
    bound_mock.assert_not_called()


async def test_email_route_missing_envelope_fails_closed(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Legacy caller passing ``inbound_text`` only (no headers) can't
    be guardrailed — refuse to reply."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=None,
            inbound_text="something",
        )

    assert result is None
    bound_mock.assert_not_called()


async def test_email_route_guardrail_rejects_bounces(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Delivery-status notifications skip the LLM entirely — the
    ``email_guardrails`` filter catches the subject prefix."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    envelope = _fake_email_envelope(subject="Delivery Status Notification (Failure)")

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=envelope,
        )

    assert result is None
    bound_mock.assert_not_called()


async def test_email_route_no_bound_assistant_skips(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Guardrail passes but no assistant is bound to the email channel
    for this org — silent skip. No LLM call, no send."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="should not be called"),
        ) as reply_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    reply_mock.assert_not_called()


async def test_email_reply_skips_when_contact_id_is_none(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Mailgun path can create bare conversations for unknown senders
    (``contact_id=NULL``). AI must not reply to an unresolved identity."""
    from src.app.core.ai_assistants import dispatch

    fake_email_conv.contact_id = None
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="A helpful reply"),
        ) as reply_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    # Contact-id gate fires BEFORE the LLM call so we don't burn tokens
    # generating a reply we can't deliver.
    reply_mock.assert_not_called()


async def test_email_reply_skips_when_empty_llm_reply(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Stop-keyword / budget-cap / empty-KB fallback → ``reply_once``
    returns "". No send attempted."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.app.shared.email.org_sender.resolve_org_sender",
            new=AsyncMock(return_value=SimpleNamespace()),
        ) as resolve_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    resolve_mock.assert_not_called()


async def test_email_reply_skips_when_no_org_sender(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Org has no verified SMTP sender AND no live OAuth mailbox.
    Nothing to send from — skip without raising."""
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="Yes we have those in stock."),
        ),
        patch(
            "src.app.shared.email.org_sender.resolve_org_sender",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.conversations.adapters.email.send_email",
            new=AsyncMock(return_value=None),
        ) as send_mock,
    ):
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
    send_mock.assert_not_called()


async def test_email_reply_dispatches_via_smtp_sender(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Happy path — SMTP backend. Guardrail passes, assistant bound,
    contact resolved, LLM replies, backend resolved as SMTP → call
    ``send_email`` with ``smtp_sender_id`` + ``ai_assistant_id`` +
    correctly-composed threading headers."""
    from src.app.core.ai_assistants import dispatch
    from src.app.shared.email.org_sender import OrgSmtpBackend

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())
    fake_smtp_sender = SimpleNamespace(id=uuid.uuid4())
    fake_backend = OrgSmtpBackend.__new__(OrgSmtpBackend)
    object.__setattr__(fake_backend, "sender", fake_smtp_sender)

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="Yes, our brown leather 3-seater is in stock."),
        ),
        patch(
            "src.app.shared.email.org_sender.resolve_org_sender",
            new=AsyncMock(return_value=fake_backend),
        ),
        patch(
            "src.app.core.conversations.adapters.email.send_email",
            new=AsyncMock(return_value=None),
        ) as send_mock,
    ):
        await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(
                message_id="<abc123@customer.example.com>",
                references="<older@customer.example.com>",
            ),
        )

    send_mock.assert_awaited_once()
    kwargs = send_mock.call_args.kwargs
    assert kwargs["sender_user_id"] is None
    assert kwargs["ai_assistant_id"] == fake_assistant.id
    assert kwargs["smtp_sender_id"] == fake_smtp_sender.id
    assert kwargs["account_id"] is None
    assert kwargs["contact_id"] == fake_email_conv.contact_id
    assert kwargs["conversation_id"] == fake_email_conv.id
    # Threading: bare RFC-5322 id (no angle brackets) — MIME builder brackets.
    assert kwargs["in_reply_to_raw"] == "abc123@customer.example.com"
    # References chain contains BOTH the prior chain and the immediate parent.
    assert "<older@customer.example.com>" in kwargs["references_chain_raw"]
    assert "<abc123@customer.example.com>" in kwargs["references_chain_raw"]
    # Re: subject prefixed exactly once.
    assert kwargs["subject"] == "Re: Sofa enquiry"


async def test_email_reply_dispatches_via_oauth_account(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """Happy path — OAuth backend. Org uses Gmail/Microsoft instead of
    SMTP → ``account_id`` populated, ``smtp_sender_id`` None."""
    from src.app.core.ai_assistants import dispatch
    from src.app.shared.email.org_sender import OrgOauthBackend

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())
    fake_account = SimpleNamespace(id=uuid.uuid4())
    fake_backend = OrgOauthBackend.__new__(OrgOauthBackend)
    fake_backend.account = fake_account
    fake_backend.session = fake_session

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="Sure thing!"),
        ),
        patch(
            "src.app.shared.email.org_sender.resolve_org_sender",
            new=AsyncMock(return_value=fake_backend),
        ),
        patch(
            "src.app.core.conversations.adapters.email.send_email",
            new=AsyncMock(return_value=None),
        ) as send_mock,
    ):
        await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    send_mock.assert_awaited_once()
    kwargs = send_mock.call_args.kwargs
    assert kwargs["account_id"] == fake_account.id
    assert kwargs["smtp_sender_id"] is None
    assert kwargs["ai_assistant_id"] == fake_assistant.id
    assert kwargs["sender_user_id"] is None


async def test_email_reply_swallows_opt_out(fake_email_conv) -> None:  # type: ignore[no-untyped-def]
    """``send_email`` raises ``OptedOut`` when the contact previously
    unsubscribed. AI must respect it — log + silent skip, no crash."""
    from src.app.core.ai_assistants import dispatch
    from src.app.core.conversations.adapters.email import OptedOut
    from src.app.shared.email.org_sender import OrgSmtpBackend

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_assistant = SimpleNamespace(id=uuid.uuid4())
    fake_backend = OrgSmtpBackend.__new__(OrgSmtpBackend)
    object.__setattr__(fake_backend, "sender", SimpleNamespace(id=uuid.uuid4()))

    async def _raise_opted_out(*_args, **_kwargs):
        raise OptedOut(contact_id=fake_email_conv.contact_id)

    with (
        patch("config.AI_EMAIL_INBOUND_ENABLED", True),
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_assistant),
        ),
        patch(
            "src.app.core.ai_assistants.runtime.reply_once",
            new=AsyncMock(return_value="A reply"),
        ),
        patch(
            "src.app.shared.email.org_sender.resolve_org_sender",
            new=AsyncMock(return_value=fake_backend),
        ),
        patch(
            "src.app.core.conversations.adapters.email.send_email",
            new=_raise_opted_out,
        ),
    ):
        # Should complete without re-raising.
        result = await dispatch.route_email_inbound(
            fake_session,
            conversation=fake_email_conv,
            inbound_email=_fake_email_envelope(),
        )

    assert result is None
