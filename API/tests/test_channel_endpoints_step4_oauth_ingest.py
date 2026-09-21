"""Coverage for Step 4 of tasks/email-endpoint-abstraction/.

Extends the OAuth ingest path (Gmail + Microsoft via ``receive_email``)
to stamp ``payload.endpoint_id`` on persisted messages. Byte-identical
to the pre-refactor OAuth output except for the new field.

Verifies:

  * :func:`_persist_inbound_email` accepts the new ``endpoint_id``
    kwarg and stamps it into ``Message.payload`` when non-None.
  * When ``endpoint_id`` is None, the payload keys match the shipped
    OAuth shape byte-for-byte (no extra key).
  * The OAuth endpoint resolver caches results per-account so a burst
    of N inbound messages costs 1 DAL lookup, not N.
  * The resolver returns ``None`` (with a warning log) when no endpoint
    row exists for the account — persist still proceeds without the
    stamp.
  * Feature flag :func:`_endpoints_refactor_enabled` mirrors the mailgun
    task's flag — one env var toggles both paths.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import email as email_adapter
from src.app.core.conversations.adapters.email import (
    _clear_oauth_endpoint_cache,
    _endpoints_refactor_enabled,
    _persist_inbound_email,
    _resolve_oauth_endpoint_id,
)
from src.app.core.conversations.models import Message
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, slug: str = "s4") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_oauth_account(
    session, org_id: uuid.UUID, email: str = "asha@yourstore.com"
) -> EmailAccount:
    row = EmailAccount(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        provider=EmailAccountProvider.gmail,
        external_account_id=email,
        email_address=email,
        display_name="Asha",
        access_token_enc="enc",
        refresh_token_enc="enc",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes_granted=[],
        sync_state=EmailAccountSyncState.live,
        daily_sent_count=0,
        daily_sent_reset_at=datetime.now(UTC),
        connected_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def _make_oauth_endpoint(
    session, *, org_id: uuid.UUID, account_id: uuid.UUID, label: str
) -> ChannelEndpoint:
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="oauth_mailbox",
        label=label,
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        oauth_account_id=account_id,
    )
    session.add(details)
    await session.flush()
    return endpoint


async def _make_contact(session, org_id: uuid.UUID, email: str) -> Contact:
    now = datetime.now(UTC)
    c = Contact(
        id=uuid.uuid4(),
        org_id=org_id,
        full_name="Cust",
        email=email,
        created_at=now,
        updated_at=now,
    )
    session.add(c)
    await session.flush()
    return c


@pytest.fixture(autouse=True)
def _reset_oauth_endpoint_cache():
    """Every test starts with an empty resolver cache."""
    _clear_oauth_endpoint_cache()
    yield
    _clear_oauth_endpoint_cache()


# ---------------------------------------------------------------------------
# 1. Feature flag
# ---------------------------------------------------------------------------


def test_flag_default_true(monkeypatch):
    monkeypatch.delenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", raising=False)
    assert _endpoints_refactor_enabled() is True


def test_flag_false_disables(monkeypatch):
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "false")
    assert _endpoints_refactor_enabled() is False


# ---------------------------------------------------------------------------
# 2. _persist_inbound_email — endpoint_id stamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_stamps_endpoint_id_when_passed(test_db):
    org = await _make_org(test_db)
    contact = await _make_contact(test_db, org.id, "customer@ex.com")
    await test_db.commit()

    ep_id = uuid.uuid4()
    msg = await _persist_inbound_email(
        test_db,
        org_id=org.id,
        contact_id=contact.id,
        headers={
            "from": "customer@ex.com",
            "to": "asha@yourstore.com",
            "subject": "Hi",
            "message-id": f"<{uuid.uuid4().hex}@ex>",
        },
        body_text="body",
        body_html=None,
        attachments=[],
        channel_message_id=f"<{uuid.uuid4().hex}@ex>",
        thread_keys=set(),
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result=None,
        dkim_result=None,
        auto_generated=False,
        source_provider="gmail",
        source_reference={"conversation_id_provider": None, "rfc_message_id": "rfc-1"},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label="asha@yourstore.com",
        endpoint_id=ep_id,
    )
    assert msg is not None
    assert msg.payload["endpoint_id"] == str(ep_id)


@pytest.mark.asyncio
async def test_persist_omits_endpoint_id_when_none(test_db):
    """Byte-identical to shipped shape when caller passes no endpoint_id."""
    org = await _make_org(test_db)
    contact = await _make_contact(test_db, org.id, "cust2@ex.com")
    await test_db.commit()

    msg = await _persist_inbound_email(
        test_db,
        org_id=org.id,
        contact_id=contact.id,
        headers={
            "from": "cust2@ex.com",
            "to": "asha@yourstore.com",
            "subject": "Hi",
            "message-id": f"<{uuid.uuid4().hex}@ex>",
        },
        body_text="body",
        body_html=None,
        attachments=[],
        channel_message_id=f"<{uuid.uuid4().hex}@ex>",
        thread_keys=set(),
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result=None,
        dkim_result=None,
        auto_generated=False,
        source_provider="gmail",
        source_reference={"conversation_id_provider": None, "rfc_message_id": "rfc-2"},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label="asha@yourstore.com",
        # endpoint_id deliberately omitted — default is None.
    )
    assert msg is not None
    assert "endpoint_id" not in msg.payload


@pytest.mark.asyncio
async def test_persist_endpoint_id_absent_default_matches_shipped_shape(test_db):
    """Explicit assertion that endpoint_id kwarg has default = None."""
    import inspect

    sig = inspect.signature(_persist_inbound_email)
    assert "endpoint_id" in sig.parameters
    assert sig.parameters["endpoint_id"].default is None


# ---------------------------------------------------------------------------
# 3. _resolve_oauth_endpoint_id — lookup + cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_returns_endpoint_id_for_matching_account(test_db):
    org = await _make_org(test_db, "resolver-hit")
    account = await _make_oauth_account(test_db, org.id)
    endpoint = await _make_oauth_endpoint(
        test_db, org_id=org.id, account_id=account.id, label=account.email_address
    )
    await test_db.commit()

    resolved = await _resolve_oauth_endpoint_id(test_db, account)
    assert resolved == endpoint.id


@pytest.mark.asyncio
async def test_resolver_returns_none_when_no_endpoint_row(test_db, caplog):
    """Account without a backing endpoint → warning logged, None returned."""
    org = await _make_org(test_db, "resolver-miss")
    account = await _make_oauth_account(test_db, org.id, email="no-endpoint@ex.com")
    await test_db.commit()

    with caplog.at_level("WARNING"):
        resolved = await _resolve_oauth_endpoint_id(test_db, account)
    assert resolved is None
    assert any("no active endpoint" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_resolver_caches_across_calls_no_n_plus_1(test_db):
    """Two calls to resolver → one call to find_active_for_org."""
    org = await _make_org(test_db, "cache-test")
    account = await _make_oauth_account(test_db, org.id, email="cache@ex.com")
    await _make_oauth_endpoint(
        test_db, org_id=org.id, account_id=account.id, label=account.email_address
    )
    await test_db.commit()

    with patch(
        "src.app.core.conversations.adapters.email.endpoints_da.find_active_for_org",
        new_callable=AsyncMock,
        wraps=email_adapter.endpoints_da.find_active_for_org,
    ) as spy:
        # First call — cache miss → DAL query.
        _ = await _resolve_oauth_endpoint_id(test_db, account)
        # Ten more calls — should all hit cache, zero more DAL queries.
        for _ in range(10):
            _ = await _resolve_oauth_endpoint_id(test_db, account)
    assert spy.await_count == 1, (
        f"expected 1 DAL call (N+1 avoidance), got {spy.await_count}"
    )


@pytest.mark.asyncio
async def test_resolver_does_not_leak_across_accounts(test_db):
    """Cache is keyed by account.id — a second account misses cache and refetches."""
    org = await _make_org(test_db, "isolation")
    acc_a = await _make_oauth_account(test_db, org.id, email="a@ex.com")
    acc_b = await _make_oauth_account(test_db, org.id, email="b@ex.com")
    ep_a = await _make_oauth_endpoint(
        test_db, org_id=org.id, account_id=acc_a.id, label="a@ex.com"
    )
    ep_b = await _make_oauth_endpoint(
        test_db, org_id=org.id, account_id=acc_b.id, label="b@ex.com"
    )
    await test_db.commit()

    got_a = await _resolve_oauth_endpoint_id(test_db, acc_a)
    got_b = await _resolve_oauth_endpoint_id(test_db, acc_b)
    assert got_a == ep_a.id
    assert got_b == ep_b.id
    # And repeated calls stay isolated
    assert await _resolve_oauth_endpoint_id(test_db, acc_a) == ep_a.id
    assert await _resolve_oauth_endpoint_id(test_db, acc_b) == ep_b.id


@pytest.mark.asyncio
async def test_resolver_scoped_by_org(test_db):
    """Endpoint in Org B does NOT resolve for Org A's account with same email."""
    org_a = await _make_org(test_db, "cross-a")
    org_b = await _make_org(test_db, "cross-b")
    acc_a = await _make_oauth_account(test_db, org_a.id, email="collide@ex.com")
    acc_b = await _make_oauth_account(test_db, org_b.id, email="collide@ex.com")
    ep_b = await _make_oauth_endpoint(
        test_db, org_id=org_b.id, account_id=acc_b.id, label="collide@ex.com"
    )
    await test_db.commit()

    # Org A has no endpoint → None.
    got_a = await _resolve_oauth_endpoint_id(test_db, acc_a)
    assert got_a is None
    # Org B resolves correctly.
    got_b = await _resolve_oauth_endpoint_id(test_db, acc_b)
    assert got_b == ep_b.id
