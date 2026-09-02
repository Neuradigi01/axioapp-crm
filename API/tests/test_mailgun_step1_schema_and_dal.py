"""Coverage for Step 1 of the mailgun-inbound track.

Verifies:

  * New columns on ``tbl_email_smtp_senders`` (``inbound_token``,
    ``capture_replies_in_crm``) and on ``tbl_messages``
    (``spf_result``, ``dkim_result``).
  * New table ``tbl_email_inbound_dlq``.
  * ``find_by_inbound_token`` DAL.
  * ``find_contact_by_email`` DAL — including cross-org isolation
    (Attacker C3 finding: threading queries take ``org_id``
    explicitly, never trust the tenant listener alone).
  * ``_generate_inbound_token`` service helper output shape.

Test-DB behaviour: ``conftest.test_db`` calls
``Base.metadata.create_all`` before each test, so every model column
+ index above is created fresh. No alembic migration is run — the
migration's backfill logic is tested by dedicated migration-level
tests in the CI's schema drift pin-test, not here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text

from src.app.core.contacts import data_access as contacts_da
from src.app.core.contacts.models import Contact
from src.app.core.email.mailgun.dlq_models import EmailInboundDlq
from src.app.core.email_senders import data_access as senders_da
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.email_senders.service import _generate_inbound_token
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_org(session, slug_suffix: str = "") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug_suffix or 'x'}",
        slug=f"step1-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


def _make_sender(*, org_id: uuid.UUID, inbound_token: str) -> EmailSmtpSender:
    return EmailSmtpSender(
        id=uuid.uuid4(),
        org_id=org_id,
        from_address=f"sender-{uuid.uuid4().hex[:8]}@example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user",
        smtp_password_enc="ciphertext-placeholder",
        tls_mode="starttls",
        inbound_token=inbound_token,
    )


def _make_contact(
    *,
    org_id: uuid.UUID,
    email: str | None,
    updated_at: datetime | None = None,
    anonymised_at: datetime | None = None,
) -> Contact:
    now = datetime.now(UTC)
    return Contact(
        id=uuid.uuid4(),
        org_id=org_id,
        full_name=f"Contact {uuid.uuid4().hex[:6]}",
        email=email,
        anonymised_at=anonymised_at,
        created_at=now,
        updated_at=updated_at or now,
    )


# ---------------------------------------------------------------------------
# Schema — columns present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_sender_row_carries_inbound_token_and_capture_columns(test_db):
    org = await _make_org(test_db)
    tok = _generate_inbound_token()
    sender = _make_sender(org_id=org.id, inbound_token=tok)
    test_db.add(sender)
    await test_db.commit()
    await test_db.refresh(sender)

    assert sender.inbound_token == tok
    # Server default is True.
    assert sender.capture_replies_in_crm is True


@pytest.mark.asyncio
async def test_message_row_carries_spf_dkim_columns(test_db):
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_messages'
               AND column_name IN ('spf_result', 'dkim_result')
            """
        )
    )
    cols = {row[0] for row in result}
    assert cols == {"spf_result", "dkim_result"}


@pytest.mark.asyncio
async def test_email_inbound_dlq_table_exists_with_expected_columns(test_db):
    """DLQ table registered via ``email.mailgun.__init__`` import chain."""
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_email_inbound_dlq'
            """
        )
    )
    cols = {row[0] for row in result}
    assert {
        "id",
        "org_id",
        "mailgun_delivery_id",
        "pending_inbound_path",
        "error_reason",
        "error_details",
        "retry_count",
        "created_at",
        "resolved_at",
    }.issubset(cols)


@pytest.mark.asyncio
async def test_email_inbound_dlq_insert_and_read_round_trip(test_db):
    org = await _make_org(test_db)
    row = EmailInboundDlq(
        org_id=org.id,
        mailgun_delivery_id="abc-123",
        pending_inbound_path="/storage/pending-inbound/xyz",
        error_reason="worker_exhausted",
        error_details={"traceback": "..."},
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fetched = (
        await test_db.execute(select(EmailInboundDlq).where(EmailInboundDlq.id == row.id))
    ).scalar_one()
    assert fetched.mailgun_delivery_id == "abc-123"
    assert fetched.error_reason == "worker_exhausted"
    assert fetched.retry_count == 0  # server default
    assert fetched.resolved_at is None


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


def test_generate_inbound_token_is_12_chars_urlsafe():
    tok = _generate_inbound_token()
    assert len(tok) == 12
    # URL-safe base64 alphabet: A-Za-z0-9-_
    import string

    allowed = set(string.ascii_letters + string.digits + "-_")
    assert set(tok).issubset(allowed)


def test_generate_inbound_token_is_random():
    tokens = {_generate_inbound_token() for _ in range(1000)}
    # 1000 draws from a ~60-bit space — collisions are ~1e-15 per pair;
    # any dup here would signal a fundamentally broken generator.
    assert len(tokens) == 1000


# ---------------------------------------------------------------------------
# find_by_inbound_token DAL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_by_inbound_token_returns_sender(test_db):
    org = await _make_org(test_db)
    tok = _generate_inbound_token()
    sender = _make_sender(org_id=org.id, inbound_token=tok)
    test_db.add(sender)
    await test_db.commit()

    found = await senders_da.find_by_inbound_token(test_db, tok)
    assert found is not None
    assert found.id == sender.id
    assert found.org_id == org.id


@pytest.mark.asyncio
async def test_find_by_inbound_token_returns_none_when_absent(test_db):
    result = await senders_da.find_by_inbound_token(test_db, "nonexistent-token")
    assert result is None


@pytest.mark.asyncio
async def test_inbound_token_unique_constraint_enforced(test_db):
    """Two rows in different orgs cannot share the same token — the
    UNIQUE constraint is on the column, not scoped by org."""
    org_a = await _make_org(test_db, slug_suffix="a")
    org_b = await _make_org(test_db, slug_suffix="b")
    shared_token = _generate_inbound_token()
    test_db.add(_make_sender(org_id=org_a.id, inbound_token=shared_token))
    await test_db.commit()

    test_db.add(_make_sender(org_id=org_b.id, inbound_token=shared_token))
    with pytest.raises(Exception):  # IntegrityError wraps to sa.exc.IntegrityError
        await test_db.commit()
    await test_db.rollback()


# ---------------------------------------------------------------------------
# find_contact_by_email DAL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_contact_by_email_returns_none_when_no_match(test_db):
    org = await _make_org(test_db)
    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org.id, email="ghost@nowhere.com"
    )
    assert result is None


@pytest.mark.asyncio
async def test_find_contact_by_email_returns_single_match(test_db):
    org = await _make_org(test_db)
    contact = _make_contact(org_id=org.id, email="Alice@Example.COM")
    test_db.add(contact)
    await test_db.commit()

    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org.id, email="alice@example.com"
    )
    assert result is not None
    assert result.id == contact.id


@pytest.mark.asyncio
async def test_find_contact_by_email_lowercases_input(test_db):
    org = await _make_org(test_db)
    contact = _make_contact(org_id=org.id, email="mixed@Case.com")
    test_db.add(contact)
    await test_db.commit()

    for probe in ("mixed@case.com", "MIXED@CASE.COM", "Mixed@Case.Com", "  mixed@case.com  "):
        result = await contacts_da.find_contact_by_email(
            test_db, org_id=org.id, email=probe
        )
        assert result is not None, f"Failed to match probe: {probe!r}"
        assert result.id == contact.id


@pytest.mark.asyncio
async def test_find_contact_by_email_returns_most_recently_updated_on_tie(test_db):
    """Same org, same email, two contacts — return the newer one."""
    org = await _make_org(test_db)
    now = datetime.now(UTC)
    older = _make_contact(
        org_id=org.id, email="dup@ex.com", updated_at=now - timedelta(days=10)
    )
    newer = _make_contact(org_id=org.id, email="dup@ex.com", updated_at=now)
    test_db.add(older)
    test_db.add(newer)
    await test_db.commit()

    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org.id, email="dup@ex.com"
    )
    assert result is not None
    assert result.id == newer.id


@pytest.mark.asyncio
async def test_find_contact_by_email_scoped_by_org_id_no_cross_org_leak(test_db):
    """The Attacker C3 case: a contact with the same email in Org B
    must NOT be returned when the caller asks for Org A. Test
    explicitly, not just via the ambient tenant listener."""
    org_a = await _make_org(test_db, slug_suffix="a")
    org_b = await _make_org(test_db, slug_suffix="b")
    contact_b = _make_contact(org_id=org_b.id, email="shared@ex.com")
    test_db.add(contact_b)
    await test_db.commit()

    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org_a.id, email="shared@ex.com"
    )
    assert result is None, "Cross-org contact leaked into Org A lookup"


@pytest.mark.asyncio
async def test_find_contact_by_email_ignores_anonymised(test_db):
    """DPDP-wiped contacts must not be re-matched by inbound flows."""
    org = await _make_org(test_db)
    anon = _make_contact(
        org_id=org.id,
        email="wiped@ex.com",
        anonymised_at=datetime.now(UTC),
    )
    test_db.add(anon)
    await test_db.commit()

    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org.id, email="wiped@ex.com"
    )
    assert result is None


@pytest.mark.asyncio
async def test_find_contact_by_email_ignores_null_email_rows(test_db):
    """Contacts with NULL email must not match on an empty string."""
    org = await _make_org(test_db)
    test_db.add(_make_contact(org_id=org.id, email=None))
    await test_db.commit()

    result = await contacts_da.find_contact_by_email(
        test_db, org_id=org.id, email=""
    )
    assert result is None
