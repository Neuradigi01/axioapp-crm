"""Router-layer tests for the sending-domains endpoints.

Exercises the 4 endpoints via the layered ASGI app (``layered_client``
fixture). Covers permission gating, Mailgun error mapping, cross-org
404s, and the endpoint-details cascade on release.

Mailgun's HTTP client is monkey-patched at the service-module scope
so the tests never hit the network — every call goes through the same
in-process ``_FakeMailgun`` used by :mod:`test_sending_domains_service`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
from src.app.core.email_sender_setup import service as sender_service
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


_MANAGE_KEY = "email.sending_domains.manage"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _grant_keys(role_id: uuid.UUID, *keys: str) -> None:
    """Idempotently insert ``(role_id, permission_id)`` grants."""
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(layered_client, *, org_slug: str, email: str, password: str) -> str:
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _dns_records(domain: str, *, valid: str = "unknown") -> dict[str, Any]:
    return {
        "sending": [
            {
                "record_type": "TXT",
                "name": f"smtp._domainkey.{domain}",
                "value": "v=DKIM1; k=rsa; p=MIIB...",
                "priority": None,
                "valid": valid,
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": domain,
                "value": "v=spf1 include:mailgun.org ~all",
                "priority": None,
                "valid": valid,
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": f"_dmarc.{domain}",
                "value": "v=DMARC1; p=none;",
                "priority": None,
                "valid": valid,
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
                "valid": valid,
                "cached": [],
                "is_active": True,
            }
        ],
    }


class _FakeMailgun:
    """Test double for :class:`MailgunApiClient`.

    The service instantiates the client itself (``client=None`` path);
    the ``_fake_mailgun`` fixture monkey-patches the class so every
    construction returns an instance backed by :data:`_shared_state`.
    Tests write into that state to drive responses + inspect calls.
    """

    def __init__(self, *, region: str = "us", **_ignore: Any) -> None:
        self.region = region

    async def create_domain(self, domain: str) -> DomainCreateResult:
        _shared_state["calls"].append(("create_domain", domain))
        return DomainCreateResult(
            mailgun_domain_id="mg-fake-123",
            name=domain,
            state="unverified",
            type="custom",
            created_at="Mon, 21 Sep 2026 00:00:00 UTC",
            sending_dns_records=_dns_records(domain)["sending"],
            receiving_dns_records=_dns_records(domain)["receiving"],
        )

    async def verify_domain(self, domain: str) -> DomainDetail:
        _shared_state["calls"].append(("verify_domain", domain))
        records = _dns_records(domain, valid="valid")
        return DomainDetail(
            mailgun_domain_id="mg-fake-123",
            name=domain,
            state="active",
            type="custom",
            created_at="Mon, 21 Sep 2026 00:00:00 UTC",
            sending_dns_records=records["sending"],
            receiving_dns_records=records["receiving"],
        )

    async def delete_domain(self, domain: str) -> None:
        _shared_state["calls"].append(("delete_domain", domain))


_shared_state: dict[str, Any] = {"calls": []}


@pytest.fixture
def fake_mailgun(monkeypatch):
    """Replace ``service.MailgunApiClient`` with :class:`_FakeMailgun`.

    Resets the shared call log so per-test assertions on ``.calls`` are
    isolated.
    """
    _shared_state["calls"] = []
    monkeypatch.setattr(sender_service, "MailgunApiClient", _FakeMailgun)
    return _shared_state


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session against the live DB. Neuter it
    in tests so nothing tries to hit a real DB outside test_engine."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sender_service.audit, "log", _noop)


async def _seed_domain(
    *,
    org_id: uuid.UUID,
    domain: str,
    verification_status: str = VERIFICATION_STATUS_PENDING,
    mailgun_domain_id: str = "mg-seed-1",
) -> uuid.UUID:
    from tests.conftest import TestSession

    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id=mailgun_domain_id,
        dns_records=_dns_records(domain),
        verification_status=verification_status,
    )
    async with TestSession() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row.id


async def _seed_bare_org(name: str = "Other Org") -> uuid.UUID:
    from tests.conftest import TestSession

    org_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_id,
                name=name,
                slug=f"other-{uuid.uuid4().hex[:8]}",
            )
        )
        await session.commit()
    return org_id


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


async def test_claim_endpoint_owner_only_403_for_admin(layered_client, seeded_admin, fake_mailgun):
    # Grant an unrelated key so the role authenticates but lacks the
    # Owner-only sending-domains permission.
    await _grant_keys(seeded_admin["role"].id, "contacts.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/sender-domains",
        json={"domain": "denied.example"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
    # Mailgun was never called — permission gate short-circuited.
    assert fake_mailgun["calls"] == []


async def test_claim_endpoint_conflict_returns_409_with_reason(
    layered_client, seeded_admin, fake_mailgun
):
    # Seed a claim on a DIFFERENT org for this exact domain — the
    # caller's org must see a 409 without revealing the owner.
    other_org = await _seed_bare_org("Other")
    await _seed_domain(org_id=other_org, domain="taken.example")

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/sender-domains",
        json={"domain": "taken.example"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    detail = body.get("detail") or body.get("message") or ""
    assert "taken.example" in detail
    # 409 must not leak the owning org.
    assert str(other_org) not in detail
    # And uniqueness fired BEFORE Mailgun was called.
    assert fake_mailgun["calls"] == []


async def test_claim_endpoint_invalid_domain_returns_422(
    layered_client, seeded_admin, fake_mailgun
):
    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/sender-domains",
        json={"domain": "https://not-a-domain.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text
    assert fake_mailgun["calls"] == []


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def test_list_endpoint_returns_domains_scoped_to_org(
    layered_client, seeded_admin, fake_mailgun
):
    own_org = seeded_admin["org"].id
    other_org = await _seed_bare_org("Neighbor")
    await _seed_domain(org_id=own_org, domain="mine-a.example")
    await _seed_domain(org_id=own_org, domain="mine-b.example")
    await _seed_domain(org_id=other_org, domain="theirs.example")

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/sender-domains",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    domains = {row["domain"] for row in body}
    assert domains == {"mine-a.example", "mine-b.example"}


async def test_list_endpoint_never_exposes_mailgun_domain_id(
    layered_client, seeded_admin, fake_mailgun
):
    own_org = seeded_admin["org"].id
    await _seed_domain(
        org_id=own_org,
        domain="mine.example",
        mailgun_domain_id="mg-secret-should-not-leak",
    )

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/sender-domains",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    payload = resp.text
    assert "mailgun_domain_id" not in payload
    assert "mg-secret-should-not-leak" not in payload
    for row in resp.json():
        assert "mailgun_domain_id" not in row


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


async def test_verify_endpoint_triggers_service_verify(layered_client, seeded_admin, fake_mailgun):
    own_org = seeded_admin["org"].id
    domain_id = await _seed_domain(
        org_id=own_org,
        domain="ready.example",
        verification_status=VERIFICATION_STATUS_PENDING,
    )
    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        f"/api/v1/sender-domains/{domain_id}/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verification_status"] == VERIFICATION_STATUS_VERIFIED
    assert body["spf_verified"] is True
    assert body["dkim_verified"] is True
    assert body["dmarc_verified"] is True
    assert body["mx_verified"] is True
    assert fake_mailgun["calls"] == [("verify_domain", "ready.example")]


async def test_verify_endpoint_cross_org_returns_404(layered_client, seeded_admin, fake_mailgun):
    other_org = await _seed_bare_org("Neighbor")
    foreign_id = await _seed_domain(org_id=other_org, domain="theirs.example")

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        f"/api/v1/sender-domains/{foreign_id}/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text
    # Mailgun must NOT be called when the row isn't visible to the caller.
    assert fake_mailgun["calls"] == []


# ---------------------------------------------------------------------------
# Delete (release)
# ---------------------------------------------------------------------------


async def test_delete_endpoint_owner_only_204(layered_client, seeded_admin, fake_mailgun):
    own_org = seeded_admin["org"].id
    domain_id = await _seed_domain(
        org_id=own_org,
        domain="release-me.example",
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.delete(
        f"/api/v1/sender-domains/{domain_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204, resp.text


async def test_delete_endpoint_cross_org_returns_404(layered_client, seeded_admin, fake_mailgun):
    other_org = await _seed_bare_org("Neighbor")
    foreign_id = await _seed_domain(org_id=other_org, domain="theirs.example")

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.delete(
        f"/api/v1/sender-domains/{foreign_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text
    assert fake_mailgun["calls"] == []


async def test_delete_endpoint_calls_mailgun_delete_and_cascades(
    layered_client, seeded_admin, fake_mailgun
):
    """The DELETE endpoint invokes Mailgun's DELETE and nulls the
    ``tbl_email_endpoint_details.domain_id`` FK for every endpoint
    that pointed at the released domain."""
    from tests.conftest import TestSession

    own_org = seeded_admin["org"].id
    domain_id = await _seed_domain(
        org_id=own_org,
        domain="cascade.example",
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )

    # Seed a custom-domain endpoint pointing at this domain.
    endpoint_id = uuid.uuid4()
    async with TestSession() as session:
        endpoint = ChannelEndpoint(
            id=endpoint_id,
            org_id=own_org,
            channel=CHANNEL_EMAIL,
            endpoint_type=ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND,
            label="cascade.example inbound",
        )
        session.add(endpoint)
        await session.flush()
        session.add(
            EmailEndpointDetails(
                endpoint_id=endpoint.id,
                org_id=own_org,
                domain_id=domain_id,
            )
        )
        await session.commit()

    await _grant_keys(seeded_admin["role"].id, _MANAGE_KEY)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.delete(
        f"/api/v1/sender-domains/{domain_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204, resp.text
    assert fake_mailgun["calls"] == [("delete_domain", "cascade.example")]

    # Endpoint FK cascaded to NULL.
    async with TestSession() as session:
        result = await session.execute(
            sql_text("SELECT domain_id FROM tbl_email_endpoint_details WHERE endpoint_id = :id"),
            {"id": endpoint_id},
        )
        assert result.scalar_one() is None
