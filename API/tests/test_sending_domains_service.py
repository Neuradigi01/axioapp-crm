"""Coverage for Step 3 of tasks/email-sending-domains/.

Locks the service-layer contract: ``claim_domain`` / ``verify_domain``
/ ``release_domain`` / ``resolve_send_envelope``. Business rules,
transaction discipline, and cross-module cascade all exercised
against the real test DB. Mailgun is injected via a ``_FakeMailgun``
stand-in so the tests never hit the network.

Discipline check for the layered architecture pin-test:
  * services own commits (verified by asserting the row persists
    after the service call).
  * DAL helpers never commit (already covered by the pin-test).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text as sql_text

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.email.mailgun.api_client import (
    DomainCreateResult,
    DomainDetail,
)
from src.app.core.email.mailgun.api_client_errors import MailgunProviderError
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email_sender_setup import service
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_RELEASED,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.email_sender_setup.schemas import ClaimDomainIn
from src.app.core.email_sender_setup.service import (
    DomainAlreadyClaimedError,
    SendNotConfiguredError,
    claim_domain,
    release_domain,
    resolve_send_envelope,
    verify_organization_email_domain,
)
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """``audit.log`` opens its own session against the live DB. Best-
    effort by contract, but during tests we neuter it entirely so the
    unit tests don't spew ``sqlalchemy.exc`` in the log."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


async def _make_org(session, name: str = "Sending Domains Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"sd-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


def _dns_all_valid(domain: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "sending": [
            {
                "record_type": "TXT",
                "name": f"smtp._domainkey.{domain}",
                "value": "v=DKIM1; k=rsa; p=MIIB...",
                "priority": None,
                "valid": "valid",
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": domain,
                "value": "v=spf1 include:mailgun.org ~all",
                "priority": None,
                "valid": "valid",
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": f"_dmarc.{domain}",
                "value": "v=DMARC1; p=none;",
                "priority": None,
                "valid": "valid",
                "cached": [],
                "is_active": True,
            },
        ],
        "receiving": [
            {
                "record_type": "MX",
                "name": domain,
                "value": "mxa.mailgun.org",
                "priority": "10",
                "valid": "valid",
                "cached": [],
                "is_active": True,
            }
        ],
    }


def _dns_partial_fail(domain: str) -> dict[str, list[dict[str, Any]]]:
    payload = _dns_all_valid(domain)
    # Fail DMARC only.
    payload["sending"][2]["valid"] = "unknown"
    return payload


class _FakeMailgun:
    """Minimal MailgunApiClient stand-in.

    Records every call + returns configurable responses. Not a subclass
    of :class:`MailgunApiClient` so accidental use of a real method
    (e.g. ``._request``) fails fast rather than making an HTTP call.
    """

    def __init__(
        self,
        *,
        create_response: DomainCreateResult | None = None,
        verify_response: DomainDetail | None = None,
        verify_raises: Exception | None = None,
        delete_raises: Exception | None = None,
    ) -> None:
        self.create_response = create_response
        self.verify_response = verify_response
        self.verify_raises = verify_raises
        self.delete_raises = delete_raises
        self.calls: list[tuple[str, str]] = []

    async def create_domain(self, domain: str) -> DomainCreateResult:
        self.calls.append(("create_domain", domain))
        assert self.create_response is not None, "test forgot to seed create_response"
        return self.create_response

    async def verify_domain(self, domain: str) -> DomainDetail:
        self.calls.append(("verify_domain", domain))
        if self.verify_raises is not None:
            raise self.verify_raises
        assert self.verify_response is not None, "test forgot to seed verify_response"
        return self.verify_response

    async def delete_domain(self, domain: str) -> None:
        self.calls.append(("delete_domain", domain))
        if self.delete_raises is not None:
            raise self.delete_raises


def _create_result(domain: str, *, mailgun_domain_id: str = "mg-abc-123") -> DomainCreateResult:
    records = _dns_all_valid(domain)
    # Freshly-created domains never come back with ``valid`` — flip
    # everything to ``unknown`` so the fixture is realistic.
    for arr in records.values():
        for r in arr:
            r["valid"] = "unknown"
    return DomainCreateResult(
        mailgun_domain_id=mailgun_domain_id,
        name=domain,
        state="unverified",
        type="custom",
        created_at="Mon, 21 Sep 2026 00:00:00 UTC",
        sending_dns_records=records["sending"],
        receiving_dns_records=records["receiving"],
    )


def _detail(
    domain: str,
    *,
    all_valid: bool,
    mailgun_domain_id: str = "mg-abc-123",
) -> DomainDetail:
    records = _dns_all_valid(domain) if all_valid else _dns_partial_fail(domain)
    return DomainDetail(
        mailgun_domain_id=mailgun_domain_id,
        name=domain,
        state="active" if all_valid else "unverified",
        type="custom",
        created_at="Mon, 21 Sep 2026 00:00:00 UTC",
        sending_dns_records=records["sending"],
        receiving_dns_records=records["receiving"],
    )


# ---------------------------------------------------------------------------
# claim_domain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_domain_creates_pending_row_and_stores_dns_records_verbatim(
    test_db,
):
    org = await _make_org(test_db)
    fake = _FakeMailgun(create_response=_create_result("acme.example"))

    row = await claim_domain(
        test_db,
        org_id=org.id,
        actor_user_id=uuid.uuid4(),
        payload=ClaimDomainIn(domain="acme.example"),
        client=fake,
    )

    assert row.id is not None
    assert row.org_id == org.id
    assert row.domain == "acme.example"
    assert row.verification_status == VERIFICATION_STATUS_PENDING
    assert row.mailgun_domain_id == "mg-abc-123"
    # JSONB stored verbatim as ``{"sending": [...], "receiving": [...]}``.
    assert set(row.dns_records.keys()) == {"sending", "receiving"}
    assert row.dns_records["sending"][0]["record_type"] == "TXT"
    assert row.dns_records["receiving"][0]["record_type"] == "MX"
    assert fake.calls == [("create_domain", "acme.example")]


@pytest.mark.asyncio
async def test_claim_domain_conflict_when_domain_already_claimed_by_other_org_returns_409(
    test_db,
):
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    seeded = OrganizationEmailDomain(
        org_id=org_a.id,
        domain="shared.example",
        mailgun_domain_id="mg-first",
        dns_records={},
    )
    test_db.add(seeded)
    await test_db.commit()

    fake = _FakeMailgun(create_response=_create_result("shared.example"))
    with pytest.raises(DomainAlreadyClaimedError):
        await claim_domain(
            test_db,
            org_id=org_b.id,
            actor_user_id=uuid.uuid4(),
            payload=ClaimDomainIn(domain="shared.example"),
            client=fake,
        )
    # Mailgun must NOT be called when the local uniqueness check trips.
    assert fake.calls == []


def test_claim_domain_validates_rfc1035_labels_rejects_scheme_urls():
    """The Pydantic schema is the enforced gate on domain shape — a
    scheme-prefixed URL, a path, and internal whitespace all fail at
    payload construction time before the service ever runs."""
    from pydantic import ValidationError

    for bad in (
        "https://foo.com",
        "foo.com/bar",
        "foo com",
        "-bad.example",
        "bad-.example",
        "no-tld",
    ):
        with pytest.raises(ValidationError):
            ClaimDomainIn(domain=bad)


# ---------------------------------------------------------------------------
# verify_organization_email_domain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_domain_all_pass_flips_to_verified_zeros_failed_counter(
    test_db,
):
    org = await _make_org(test_db)
    row = OrganizationEmailDomain(
        org_id=org.id,
        domain="ready.example",
        mailgun_domain_id="mg-1",
        dns_records={},
        verification_status=VERIFICATION_STATUS_PENDING,
        consecutive_failed_checks=3,  # will be zeroed
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fake = _FakeMailgun(verify_response=_detail("ready.example", all_valid=True))
    updated = await verify_organization_email_domain(
        test_db,
        org_id=org.id,
        id=row.id,
        actor_user_id=None,
        client=fake,
    )
    assert updated.verification_status == VERIFICATION_STATUS_VERIFIED
    assert updated.consecutive_failed_checks == 0
    assert updated.mx_verified is True
    assert updated.spf_verified is True
    assert updated.dkim_verified is True
    assert updated.dmarc_verified is True
    assert updated.last_verified_at is not None


@pytest.mark.asyncio
async def test_verify_domain_any_fail_increments_failed_counter(test_db):
    org = await _make_org(test_db)
    row = OrganizationEmailDomain(
        org_id=org.id,
        domain="drifting.example",
        mailgun_domain_id="mg-2",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
        consecutive_failed_checks=2,
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fake = _FakeMailgun(verify_response=_detail("drifting.example", all_valid=False))
    updated = await verify_organization_email_domain(
        test_db,
        org_id=org.id,
        id=row.id,
        actor_user_id=None,
        client=fake,
    )
    # Counter bumped; status untouched (Step 6 cron owns transitions).
    assert updated.consecutive_failed_checks == 3
    assert updated.verification_status == VERIFICATION_STATUS_VERIFIED
    # DMARC was set to unknown so dmarc_verified must be False.
    assert updated.dmarc_verified is False


@pytest.mark.asyncio
async def test_verify_domain_mailgun_5xx_does_not_increment_failed_counter(
    test_db,
):
    org = await _make_org(test_db)
    row = OrganizationEmailDomain(
        org_id=org.id,
        domain="blip.example",
        mailgun_domain_id="mg-3",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
        consecutive_failed_checks=1,
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fake = _FakeMailgun(
        verify_raises=MailgunProviderError(
            "mailgun 502 for PUT /v4/domains/blip.example/verify",
            status_code=502,
        )
    )
    with pytest.raises(MailgunProviderError):
        await verify_organization_email_domain(
            test_db,
            org_id=org.id,
            id=row.id,
            actor_user_id=None,
            client=fake,
        )

    # Counter untouched — provider blip must not degrade the domain.
    await test_db.refresh(row)
    assert row.consecutive_failed_checks == 1
    assert row.verification_status == VERIFICATION_STATUS_VERIFIED


# ---------------------------------------------------------------------------
# release_domain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_domain_sets_status_released_and_calls_mailgun_delete(
    test_db,
):
    org = await _make_org(test_db)
    row = OrganizationEmailDomain(
        org_id=org.id,
        domain="gone.example",
        mailgun_domain_id="mg-4",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fake = _FakeMailgun()
    await release_domain(
        test_db,
        org_id=org.id,
        id=row.id,
        actor_user_id=uuid.uuid4(),
        client=fake,
    )

    await test_db.refresh(row)
    assert row.verification_status == VERIFICATION_STATUS_RELEASED
    assert row.released_at is not None
    assert fake.calls == [("delete_domain", "gone.example")]


@pytest.mark.asyncio
async def test_release_domain_cascades_endpoint_details_domain_id_to_null(
    test_db,
):
    org = await _make_org(test_db)
    domain_row = OrganizationEmailDomain(
        org_id=org.id,
        domain="cascade.example",
        mailgun_domain_id="mg-5",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    test_db.add(domain_row)
    await test_db.flush()

    endpoint = ChannelEndpoint(
        org_id=org.id,
        channel=CHANNEL_EMAIL,
        endpoint_type=ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND,
        label="cascade.example inbound",
    )
    test_db.add(endpoint)
    await test_db.flush()

    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org.id,
        domain_id=domain_row.id,
    )
    test_db.add(details)
    await test_db.commit()

    # An unrelated endpoint on ANOTHER domain in the same org — must
    # survive with its FK intact.
    other_domain = OrganizationEmailDomain(
        org_id=org.id,
        domain="untouched.example",
        mailgun_domain_id="mg-6",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    test_db.add(other_domain)
    await test_db.flush()
    other_endpoint = ChannelEndpoint(
        org_id=org.id,
        channel=CHANNEL_EMAIL,
        endpoint_type=ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND,
        label="untouched.example inbound",
    )
    test_db.add(other_endpoint)
    await test_db.flush()
    other_details = EmailEndpointDetails(
        endpoint_id=other_endpoint.id,
        org_id=org.id,
        domain_id=other_domain.id,
    )
    test_db.add(other_details)
    await test_db.commit()

    fake = _FakeMailgun()
    await release_domain(
        test_db,
        org_id=org.id,
        id=domain_row.id,
        actor_user_id=uuid.uuid4(),
        client=fake,
    )

    # The details row survives, but its domain_id is now NULL.
    result = await test_db.execute(
        sql_text("SELECT domain_id FROM tbl_email_endpoint_details WHERE endpoint_id = :id"),
        {"id": endpoint.id},
    )
    assert result.scalar_one() is None

    # Unrelated endpoint's FK is untouched.
    result = await test_db.execute(
        sql_text("SELECT domain_id FROM tbl_email_endpoint_details WHERE endpoint_id = :id"),
        {"id": other_endpoint.id},
    )
    assert result.scalar_one() == other_domain.id


# ---------------------------------------------------------------------------
# resolve_send_envelope
# ---------------------------------------------------------------------------


async def _make_smtp_sender(
    session,
    *,
    org_id: uuid.UUID,
    from_address: str,
    is_default: bool = False,
    verified: bool = True,
) -> EmailSmtpSender:
    sender = EmailSmtpSender(
        org_id=org_id,
        from_address=from_address,
        display_name="Sales",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username=from_address,
        smtp_password_enc="fake-fernet-ciphertext",
        tls_mode="starttls",
        verified_at=datetime.now(UTC) if verified else None,
        is_default=is_default,
        inbound_token=uuid.uuid4().hex[:12],
    )
    session.add(sender)
    await session.flush()
    return sender


async def _make_oauth_account(
    session,
    *,
    org_id: uuid.UUID,
    email_address: str,
    is_default: bool = False,
) -> EmailAccount:
    account = EmailAccount(
        org_id=org_id,
        user_id=uuid.uuid4(),
        provider=EmailAccountProvider.gmail,
        external_account_id=f"ext-{uuid.uuid4().hex[:8]}",
        email_address=email_address,
        display_name="Rep",
        access_token_enc="access-fake",
        refresh_token_enc="refresh-fake",
        sync_state=EmailAccountSyncState.live,
        is_default=is_default,
    )
    session.add(account)
    await session.flush()
    return account


@pytest.mark.asyncio
async def test_resolve_send_envelope_prefers_caller_supplied_sender(test_db):
    org = await _make_org(test_db)
    default_smtp = await _make_smtp_sender(
        test_db, org_id=org.id, from_address="default@example.com", is_default=True
    )
    caller_smtp = await _make_smtp_sender(
        test_db, org_id=org.id, from_address="explicit@example.com"
    )
    await test_db.commit()

    envelope = await resolve_send_envelope(
        test_db, org_id=org.id, caller_supplied_sender_id=caller_smtp.id
    )
    assert envelope.envelope_type == "smtp_sender"
    assert envelope.smtp_sender_id == caller_smtp.id
    assert envelope.reply_to == "explicit@example.com"
    # Default was ignored.
    assert envelope.smtp_sender_id != default_smtp.id


@pytest.mark.asyncio
async def test_resolve_send_envelope_falls_to_verified_own_domain(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.crm")
    org = await _make_org(test_db)
    domain_row = OrganizationEmailDomain(
        org_id=org.id,
        domain="verified.example",
        mailgun_domain_id="mg-8",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    test_db.add(domain_row)
    await test_db.commit()
    await test_db.refresh(domain_row)

    envelope = await resolve_send_envelope(test_db, org_id=org.id)
    assert envelope.envelope_type == "own_domain"
    assert envelope.own_domain_id == domain_row.id
    assert envelope.from_address == "no-reply@verified.example"
    assert envelope.dispatch_domain == "verified.example"


@pytest.mark.asyncio
async def test_resolve_send_envelope_skips_demoted_own_domain(test_db, monkeypatch):
    """A demoted domain must never win the cascade — the envelope
    should fall through to platform-from."""
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.crm")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.crm")
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailDomain(
            org_id=org.id,
            domain="demoted.example",
            mailgun_domain_id="mg-9",
            dns_records={},
            verification_status=VERIFICATION_STATUS_DEMOTED,
        )
    )
    await test_db.commit()

    envelope = await resolve_send_envelope(test_db, org_id=org.id)
    assert envelope.envelope_type == "platform_from"
    assert envelope.dispatch_domain == "platform.crm"


@pytest.mark.asyncio
async def test_resolve_send_envelope_falls_to_platform_from_when_no_own_domain(
    test_db, monkeypatch
):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.crm")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.crm")
    org = await _make_org(test_db)
    await test_db.commit()

    envelope = await resolve_send_envelope(test_db, org_id=org.id)
    assert envelope.envelope_type == "platform_from"
    assert envelope.from_address == f"org-{org.id}@platform.crm"
    assert envelope.reply_to == "no-reply@reply.platform.crm"
    assert envelope.dispatch_domain == "platform.crm"


@pytest.mark.asyncio
async def test_resolve_send_envelope_raises_send_not_configured_when_all_paths_miss(
    test_db, monkeypatch
):
    monkeypatch.delenv("EMAIL_PLATFORM_SENDING_DOMAIN", raising=False)
    org = await _make_org(test_db)
    await test_db.commit()

    with pytest.raises(SendNotConfiguredError):
        await resolve_send_envelope(test_db, org_id=org.id)


# ---------------------------------------------------------------------------
# Recovery transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_after_demotion_notifies_owner(test_db):
    """A demoted domain that returns all-pass on the next ``/verify``
    must transition back to ``verified``, clear the demoted stamp, and
    fire an audit ``sending_domain.verified`` event (audit is
    monkey-patched to capture the call)."""
    audit_calls: list[dict[str, Any]] = []

    async def _capture(*args, **kwargs):
        audit_calls.append({"args": args, "kwargs": kwargs})

    org = await _make_org(test_db)
    row = OrganizationEmailDomain(
        org_id=org.id,
        domain="recovered.example",
        mailgun_domain_id="mg-10",
        dns_records={},
        verification_status=VERIFICATION_STATUS_DEMOTED,
        consecutive_failed_checks=5,
    )
    row.demoted_at = datetime.now(UTC)
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    fake = _FakeMailgun(verify_response=_detail("recovered.example", all_valid=True))
    with patch.object(service.audit, "log", _capture):
        updated = await verify_organization_email_domain(
            test_db,
            org_id=org.id,
            id=row.id,
            actor_user_id=None,
            client=fake,
        )
    assert updated.verification_status == VERIFICATION_STATUS_VERIFIED
    assert updated.demoted_at is None
    assert updated.consecutive_failed_checks == 0
    # Owner notification = the audit-log side-effect on the recovery
    # transition. Prior status must be recorded so downstream notif
    # workers can tell "first verify" from "post-demote recovery".
    assert audit_calls, "audit.log was not invoked"
    call = audit_calls[0]
    # ``audit.log`` takes ``action`` as its first positional arg.
    assert call["args"][0] == "sending_domain.verified"
    assert call["kwargs"]["after"]["prior_status"] == VERIFICATION_STATUS_DEMOTED
    assert call["kwargs"]["after"]["new_status"] == VERIFICATION_STATUS_VERIFIED
