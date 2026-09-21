"""Coverage for :mod:`conversations.adapters.email_platform_from` (Step 5a).

Tests the envelope-composition helper + reply-token resolver in
isolation from the send cascade. The send-cascade integration itself
lands in Step 5b and gets its own end-to-end coverage there.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
    ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.conversations.adapters.email_platform_from import (
    FIRST_USE_NOTIFICATION_TYPE,
    PlatformEnvelope,
    PlatformFromNotConfiguredError,
    already_notified_first_platform_from,
    build_platform_envelope,
    resolve_or_create_platform_reply_token,
)
from src.app.core.notifications.models import Notification
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "PF Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"pf-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


# ---------------------------------------------------------------------------
# build_platform_envelope
# ---------------------------------------------------------------------------


def test_build_platform_envelope_composes_from_and_reply_to():
    org_id = uuid.uuid4()
    env = build_platform_envelope(
        org_id=org_id,
        reply_token="tok12345",
        platform_domain="mail.crm.example",
        inbound_domain="reply.crm.example",
    )
    assert isinstance(env, PlatformEnvelope)
    assert env.from_address == f"org-{org_id}@mail.crm.example"
    assert env.reply_to == "r-tok12345@reply.crm.example"
    assert env.dispatch_domain == "mail.crm.example"


def test_build_platform_envelope_uses_full_uuid_local_part():
    org_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    env = build_platform_envelope(
        org_id=org_id,
        reply_token="tok",
        platform_domain="mail.crm.example",
        inbound_domain="reply.crm.example",
    )
    # UUID must appear verbatim — spec locks this ("no PII leak, no
    # directory enumeration"). No truncation.
    assert str(org_id) in env.from_address


def test_build_platform_envelope_reads_env_when_domains_none(monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "env-mail.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "env-reply.example")
    env = build_platform_envelope(org_id=uuid.uuid4(), reply_token="tok")
    assert env.dispatch_domain == "env-mail.example"
    assert env.reply_to.endswith("@env-reply.example")


def test_build_platform_envelope_falls_back_inbound_to_platform(monkeypatch):
    """When ``INBOUND_EMAIL_DOMAIN`` isn't set, the inbound side reuses
    the platform domain — the single-tenant-shared-Mailgun deployment."""
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "shared.example")
    monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
    env = build_platform_envelope(org_id=uuid.uuid4(), reply_token="tok")
    assert env.dispatch_domain == "shared.example"
    assert env.reply_to.endswith("@shared.example")


def test_build_platform_envelope_raises_when_platform_domain_missing(
    monkeypatch,
):
    monkeypatch.delenv("EMAIL_PLATFORM_SENDING_DOMAIN", raising=False)
    with pytest.raises(PlatformFromNotConfiguredError):
        build_platform_envelope(org_id=uuid.uuid4(), reply_token="tok")


# ---------------------------------------------------------------------------
# resolve_or_create_platform_reply_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_token_reuses_existing_smtp_reply_capture(test_db):
    """When the org has an active ``smtp_reply_capture`` endpoint, its
    reply_token is reused — platform-from replies land in the same
    inbox as SMTP-sender replies."""
    org = await _make_org(test_db)
    # Seed an SMTP reply-capture endpoint by hand.
    endpoint = ChannelEndpoint(
        org_id=org.id,
        channel=CHANNEL_EMAIL,
        endpoint_type=ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
        label="smtp cap",
    )
    test_db.add(endpoint)
    await test_db.flush()
    test_db.add(
        EmailEndpointDetails(
            endpoint_id=endpoint.id,
            org_id=org.id,
            reply_token="smtp-shared-token",
        )
    )
    await test_db.commit()

    token, created = await resolve_or_create_platform_reply_token(test_db, org_id=org.id)
    assert token == "smtp-shared-token"
    assert created is False
    # No new platform_reply_capture endpoint was created.
    rows = await test_db.execute(
        select(ChannelEndpoint).where(
            ChannelEndpoint.org_id == org.id,
            ChannelEndpoint.endpoint_type == ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
        )
    )
    assert rows.first() is None


@pytest.mark.asyncio
async def test_resolve_token_creates_platform_endpoint_on_first_call(test_db):
    org = await _make_org(test_db)
    token, created = await resolve_or_create_platform_reply_token(test_db, org_id=org.id)
    assert token
    assert created is True
    # Endpoint + details rows now exist.
    endpoint_row = (
        await test_db.execute(
            select(ChannelEndpoint).where(
                ChannelEndpoint.org_id == org.id,
                ChannelEndpoint.endpoint_type == ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
            )
        )
    ).scalar_one()
    details_row = (
        await test_db.execute(
            select(EmailEndpointDetails).where(EmailEndpointDetails.endpoint_id == endpoint_row.id)
        )
    ).scalar_one()
    assert details_row.reply_token == token
    # No sender FK attached — this endpoint is org-wide.
    assert details_row.smtp_sender_id is None
    assert details_row.oauth_account_id is None
    assert details_row.domain_id is None


@pytest.mark.asyncio
async def test_resolve_token_reuses_existing_platform_endpoint(test_db):
    """Second call for the same org reuses the previously created
    platform_reply_capture endpoint — no duplicate rows."""
    org = await _make_org(test_db)
    token_a, created_a = await resolve_or_create_platform_reply_token(test_db, org_id=org.id)
    await test_db.commit()
    token_b, created_b = await resolve_or_create_platform_reply_token(test_db, org_id=org.id)
    assert token_a == token_b
    assert created_a is True
    assert created_b is False
    # Still exactly one endpoint row.
    count = (
        await test_db.execute(
            select(ChannelEndpoint).where(
                ChannelEndpoint.org_id == org.id,
                ChannelEndpoint.endpoint_type == ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
            )
        )
    ).all()
    assert len(count) == 1


# ---------------------------------------------------------------------------
# already_notified_first_platform_from
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_notified_false_when_no_prior_notification(test_db):
    org = await _make_org(test_db)
    await test_db.commit()
    assert await already_notified_first_platform_from(test_db, org_id=org.id) is False


@pytest.mark.asyncio
async def test_already_notified_true_after_prior_notification(test_db):
    org = await _make_org(test_db)
    test_db.add(
        Notification(
            org_id=org.id,
            user_id=uuid.uuid4(),
            type=FIRST_USE_NOTIFICATION_TYPE,
            title="You're on platform sending",
        )
    )
    await test_db.commit()
    assert await already_notified_first_platform_from(test_db, org_id=org.id) is True


@pytest.mark.asyncio
async def test_already_notified_is_org_scoped(test_db):
    """Other-org notification doesn't count."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    test_db.add(
        Notification(
            org_id=org_a.id,
            user_id=uuid.uuid4(),
            type=FIRST_USE_NOTIFICATION_TYPE,
            title="platform send",
        )
    )
    await test_db.commit()
    assert await already_notified_first_platform_from(test_db, org_id=org_b.id) is False
