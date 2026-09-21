"""Coverage for Step 4 of ``tasks/email-inbound-forwarding/``.

Two surfaces:

  A. ``core.contacts.service.auto_create_from_email`` — the RFC
     ``From:`` header → minimal :class:`Contact` factory used by the
     forwarded-address ingest path.

  B. ``core.conversations.adapters.email._persist_inbound_email`` new
     ``endpoint_type`` param — stamped into the persisted message's
     ``payload`` so downstream analytics can bucket by inbound flow.

Auto-create is deliberately kept lean: no custom-field validation,
no permission gate, no consent-event write. Callers (Mailgun ingest)
land the row NOW so the inbound message has an attach point; a staff
member fills required fields in a follow-up edit.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "AC Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"ac-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session against the live DB. Best-
    effort by contract, but during tests we neuter it entirely so the
    unit tests don't spew ``sqlalchemy.exc``."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(contacts_service.audit, "log", _noop)


# ---------------------------------------------------------------------------
# 1. Header parsing
# ---------------------------------------------------------------------------


async def test_auto_create_parses_from_header_display_name_and_email(test_db):
    org = await _make_org(test_db)
    await test_db.commit()

    contact = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header='"Asha Rao" <asha@customer.example>',
    )
    assert contact.email == "asha@customer.example"
    # Display name is composed into full_name from first + last.
    assert contact.full_name == "Asha Rao"


async def test_auto_create_parses_bare_email_from_header(test_db):
    """A ``From: sender@example.com`` with no display name lands with
    ``full_name`` falling back to the email local-part so the
    inbox-triage UI has something readable."""
    org = await _make_org(test_db)
    await test_db.commit()

    contact = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header="bare@customer.example",
    )
    assert contact.email == "bare@customer.example"
    # Fallback to local-part when no display name.
    assert contact.full_name == "bare"


async def test_auto_create_lowercases_email(test_db):
    org = await _make_org(test_db)
    await test_db.commit()

    contact = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header="  Mixed CASE <MixedCase@Customer.Example>  ",
    )
    assert contact.email == "mixedcase@customer.example"


# ---------------------------------------------------------------------------
# 2. Idempotency (pre-check + race)
# ---------------------------------------------------------------------------


async def test_auto_create_race_on_unique_email_returns_existing_contact(
    test_db,
):
    """Second call for the same email returns the FIRST contact
    (idempotency via pre-check + IntegrityError fallback). No
    duplicate row lands."""
    org = await _make_org(test_db)
    await test_db.commit()

    first = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header="Repeat <repeat@customer.example>",
    )
    second = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header='"Repeat Alt" <repeat@customer.example>',
    )
    assert second.id == first.id
    # Second call preserved the ORIGINAL name — we don't overwrite
    # a live contact from a subsequent auto-create.
    assert second.full_name == "Repeat"


async def test_auto_create_invalid_from_raises(test_db):
    from src.app.core.contacts.service import InvalidFromHeader

    org = await _make_org(test_db)
    await test_db.commit()

    for bad in ("", "no-at-sign", "spaces in address", "@no-local.com"):
        with pytest.raises(InvalidFromHeader):
            await contacts_service.auto_create_from_email(
                test_db,
                org_id=org.id,
                from_header=bad,
            )


# ---------------------------------------------------------------------------
# 3. Audit + source attribution
# ---------------------------------------------------------------------------


async def test_auto_create_writes_audit_event_with_source(test_db):
    org = await _make_org(test_db)
    await test_db.commit()

    with patch.object(contacts_service.audit, "log", new_callable=AsyncMock) as audit_mock:
        await contacts_service.auto_create_from_email(
            test_db,
            org_id=org.id,
            from_header="Aud <aud@customer.example>",
        )
    audit_mock.assert_called_once()
    args, kwargs = audit_mock.call_args
    assert args[0] == "contact.auto_created_from_inbound_email"
    assert kwargs["org_id"] == org.id
    assert kwargs["after"]["email"] == "aud@customer.example"
    assert kwargs["after"]["source"] == "email_forwarded_address"


async def test_auto_create_source_email_forwarded_address_visible_in_attribution(
    test_db,
):
    """Default ``source='email_forwarded_address'`` lands on the row
    so a lifecycle report can bucket "leads from forwarded addresses"
    without joining the audit table."""
    org = await _make_org(test_db)
    await test_db.commit()

    contact = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header="Src <src@customer.example>",
    )
    assert contact.source == "email_forwarded_address"


async def test_auto_create_custom_source_overrides_default(test_db):
    """Callers can pass a different ``source`` (e.g. future
    custom-inbound-domain flow) without touching the default."""
    org = await _make_org(test_db)
    await test_db.commit()

    contact = await contacts_service.auto_create_from_email(
        test_db,
        org_id=org.id,
        from_header="Custom <custom@customer.example>",
        source="email_custom_inbound_domain",
    )
    assert contact.source == "email_custom_inbound_domain"


# ---------------------------------------------------------------------------
# 4. _persist_inbound_email — endpoint_type stamping
# ---------------------------------------------------------------------------


async def test_persist_helper_stamps_endpoint_type_in_payload(test_db):
    """New optional ``endpoint_type`` param on ``_persist_inbound_email``
    lands in the persisted message's ``payload`` so downstream
    analytics can bucket by inbound flow."""
    from sqlalchemy import select as _sel

    from src.app.core.conversations.adapters.email import _persist_inbound_email
    from src.app.core.conversations.models import Message

    org = await _make_org(test_db)
    contact = Contact(
        org_id=org.id,
        full_name="Sender",
        email="stamp@customer.example",
        source=None,
    )
    test_db.add(contact)
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@ex.com>"
    msg = await _persist_inbound_email(
        test_db,
        org_id=org.id,
        contact_id=contact.id,
        headers={"from": "stamp@customer.example", "subject": "hi"},
        body_text="hi",
        body_html=None,
        attachments=[],
        channel_message_id=f"mg:{delivery_id}",
        thread_keys=set(),
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result="pass",
        dkim_result="pass",
        auto_generated=False,
        source_provider="mailgun",
        source_reference={"mailgun_delivery_id": delivery_id},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label=None,
        endpoint_type="forwarded_address",
    )
    assert msg is not None
    reloaded = (await test_db.execute(_sel(Message).where(Message.id == msg.id))).scalar_one()
    assert reloaded.payload["endpoint_type"] == "forwarded_address"


async def test_persist_helper_forwarded_type_skips_unknown_recipient_audit(test_db, monkeypatch):
    """Passing ``endpoint_type='forwarded_address'`` into
    ``_persist_inbound_email`` never emits a ``mailgun.inbound.
    unknown_recipient`` audit — that's a tasks.py-level dispatch
    audit, not a persist-helper concern. Regression pin: the
    persist helper doesn't accidentally start emitting mailgun-side
    audits."""
    from src.app.core.conversations.adapters import email as email_adapter
    from src.app.core.conversations.adapters.email import _persist_inbound_email

    org = await _make_org(test_db)
    contact = Contact(
        org_id=org.id,
        full_name="Sender",
        email="quiet@customer.example",
        source=None,
    )
    test_db.add(contact)
    await test_db.commit()

    calls: list[tuple[str, ...]] = []

    async def _capture(*args, **_kwargs):
        calls.append(tuple(str(a) for a in args))

    monkeypatch.setattr(email_adapter.audit, "log", _capture)

    delivery_id = f"<{uuid.uuid4().hex}@ex.com>"
    await _persist_inbound_email(
        test_db,
        org_id=org.id,
        contact_id=contact.id,
        headers={"from": "quiet@customer.example"},
        body_text="hi",
        body_html=None,
        attachments=[],
        channel_message_id=f"mg:{delivery_id}",
        thread_keys=set(),
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result="pass",
        dkim_result="pass",
        auto_generated=False,
        source_provider="mailgun",
        source_reference={"mailgun_delivery_id": delivery_id},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label=None,
        endpoint_type="forwarded_address",
    )
    unknown_recipient_events = [c for c in calls if any("unknown_recipient" in a for a in c)]
    assert unknown_recipient_events == []
