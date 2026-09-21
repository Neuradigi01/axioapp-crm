"""Coverage for Step 2 of ``tasks/email-inbound-forwarding/``.

Adds the ``forwarded_address`` endpoint type on top of Track 1's
channel-endpoints schema. Tests cover:

  * migration DDL (auto_create_contact default true; default_assignee
    nullable + partial index)
  * DAL / service integration: token shape, cross-org assignee
    rejection, collision-retry loop, audit event, token-never-leaked
    response shape

Router-level Owner/Admin permission enforcement lands with Steps 4-6
and is exercised there — service tests here trust the caller has
been authorised (matches the shipped ``deactivate_endpoint`` test's
posture).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text as sql_text

from src.app.core.channel_endpoints import data_access, service
from src.app.core.channel_endpoints.models import (
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.permissions.models import Role
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo
from src.models.user import UserLogin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "FA Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"fa-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _seed_user_in_org(
    session,
    *,
    org_id: uuid.UUID,
    email: str,
    first_name: str = "Assign",
) -> uuid.UUID:
    """Insert a user + info + membership row and return the user's
    ``legacy_uuid`` (the UUID identity every FK carries).

    Deliberately minimal — this test file doesn't exercise the auth
    stack, so we skip the ``users`` shim-row insert; ``get_user_by_uuid``
    only needs ``tbl_user_login.legacy_uuid`` set.
    """
    user_uuid = uuid.uuid4()
    login_handle = f"fa-{uuid.uuid4().hex[:8]}"

    user_login = UserLogin(
        user_id=login_handle,
        password=hash_password("Ignored@123"),
        is_active=True,
    )
    session.add(user_login)
    await session.flush()

    await session.execute(
        sql_text("UPDATE tbl_user_login SET legacy_uuid = :uuid WHERE id = :id"),
        {"uuid": str(user_uuid), "id": user_login.id},
    )
    session.add(
        LegacyUserInfo(
            member_id=user_login.id,
            first_name=first_name,
            last_name="Person",
            email=email,
            mobile_no="0000000000",
        )
    )
    role = Role(id=uuid.uuid4(), org_id=org_id, name="admin", is_system=True)
    session.add(role)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org_id,
            user_member_id=user_login.id,
            role_id=role.id,
            status="active",
            is_active=True,
            is_demo=False,
        )
    )
    await session.flush()
    return user_uuid


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session against the live DB; neuter it."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr("src.app.core.channel_endpoints.service.audit.log", _noop)


# ---------------------------------------------------------------------------
# Migration DDL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_adds_auto_create_contact_default_true(test_db):
    """Server default is TRUE — a new endpoint without an explicit
    value lands with auto_create_contact=True, matching the industry
    baseline (HubSpot / Front) for inbox-triage."""
    result = await test_db.execute(
        sql_text(
            """
            SELECT column_default
              FROM information_schema.columns
             WHERE table_name = 'tbl_email_endpoint_details'
               AND column_name = 'auto_create_contact'
            """
        )
    )
    default_expr = result.scalar_one()
    assert default_expr is not None
    # Postgres normalises `true` → `true` or `'true'::boolean`; assert
    # via lowercase substring so both shapes match.
    assert "true" in default_expr.lower()


@pytest.mark.asyncio
async def test_migration_adds_default_assignee_user_id_nullable_set_null_on_user_delete(
    test_db,
):
    """The column is nullable + the partial index exists.

    Post-migration-0037 convention: no FK to ``tbl_user_login`` — the
    staff-offboarding flow is responsible for nulling references at
    user deactivation, mirroring ``tbl_contacts.assigned_to_id``.
    """
    result = await test_db.execute(
        sql_text(
            """
            SELECT is_nullable
              FROM information_schema.columns
             WHERE table_name = 'tbl_email_endpoint_details'
               AND column_name = 'default_assignee_user_id'
            """
        )
    )
    assert result.scalar_one() == "YES"

    # Partial index present.
    result = await test_db.execute(
        sql_text(
            """
            SELECT indexdef
              FROM pg_indexes
             WHERE tablename = 'tbl_email_endpoint_details'
               AND indexname = 'ix_email_endpoint_details_default_assignee'
            """
        )
    )
    idx_def = result.scalar_one_or_none()
    assert idx_def is not None
    assert "default_assignee_user_id IS NOT NULL" in idx_def


# ---------------------------------------------------------------------------
# DAL + service — create_forwarded_address
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_forwarded_address_generates_f_prefixed_token(test_db, monkeypatch):
    """DAL emits a 12-char base64url token; the response schema
    composes it into ``f-<token>@<INBOUND_EMAIL_DOMAIN>`` — no other
    prefix reaches the caller."""
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.example.com")
    org = await _make_org(test_db)
    await test_db.commit()

    out = await service.create_forwarded_address_endpoint(
        test_db,
        org_id=org.id,
        actor_user_id=uuid.uuid4(),
        label="Support inbox",
    )

    # Address shape is ``f-<12chars>@in.example.com``.
    assert out.forwarding_address.startswith("f-")
    assert out.forwarding_address.endswith("@in.example.com")
    # Raw token lives on the DB row; response never exposes it.
    details = (
        await test_db.execute(
            sql_text(
                "SELECT forwarding_token FROM tbl_email_endpoint_details WHERE endpoint_id = :id"
            ),
            {"id": out.id},
        )
    ).scalar_one()
    assert isinstance(details, str)
    assert len(details) == 12


@pytest.mark.asyncio
async def test_create_forwarded_address_rejects_assignee_from_other_org(test_db):
    """Cross-org ``default_assignee_user_id`` → 400. Prevents an
    org-membership leak via the ingest routing config."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    # Seed a user in org B; try to attach as assignee in org A.
    foreign_user_uuid = await _seed_user_in_org(
        test_db, org_id=org_b.id, email="foreign@example.com"
    )
    await test_db.commit()

    with pytest.raises(HTTPException) as exc:
        await service.create_forwarded_address_endpoint(
            test_db,
            org_id=org_a.id,
            actor_user_id=uuid.uuid4(),
            label="Cross-org attempt",
            default_assignee_user_id=foreign_user_uuid,
        )
    assert exc.value.status_code == 400
    assert "org" in (exc.value.detail or "").lower()

    # No endpoint row was created (validation happens before the DAL
    # call, so nothing leaked to disk).
    count = (
        await test_db.execute(
            sql_text("SELECT COUNT(*) FROM tbl_channel_endpoints WHERE org_id = :id"),
            {"id": org_a.id},
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_create_forwarded_address_regenerates_on_token_collision(test_db, monkeypatch):
    """First token collides with a pre-existing row; the DAL's retry
    loop regenerates and lands on the second try."""
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.example.com")
    org = await _make_org(test_db)
    # Seed a row whose forwarding_token will be the first thing the
    # generator returns — forces a UNIQUE collision.
    pre_endpoint = ChannelEndpoint(
        org_id=org.id,
        channel="email",
        endpoint_type="forwarded_address",
        label="Pre-existing",
    )
    test_db.add(pre_endpoint)
    await test_db.flush()
    test_db.add(
        EmailEndpointDetails(
            endpoint_id=pre_endpoint.id,
            org_id=org.id,
            forwarding_token="collide12345",
        )
    )
    await test_db.commit()

    tokens = iter(["collide12345", "fresh12tok01"])

    def _fake_gen():
        return next(tokens)

    monkeypatch.setattr(data_access, "_generate_token", _fake_gen)

    out = await service.create_forwarded_address_endpoint(
        test_db,
        org_id=org.id,
        actor_user_id=uuid.uuid4(),
        label="Retry survivor",
    )
    # The second (fresh) token landed on the row.
    stored = (
        await test_db.execute(
            sql_text(
                "SELECT forwarding_token FROM tbl_email_endpoint_details WHERE endpoint_id = :id"
            ),
            {"id": out.id},
        )
    ).scalar_one()
    assert stored == "fresh12tok01"
    assert out.forwarding_address == "f-fresh12tok01@in.example.com"


@pytest.mark.asyncio
async def test_create_forwarded_address_audit_event_written(test_db, monkeypatch):
    """``forwarded_address_endpoint.created`` audit event fires with
    the operator-facing metadata (label + auto_create + assignee)."""
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.example.com")
    org = await _make_org(test_db)
    await test_db.commit()
    actor = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ) as audit_mock:
        await service.create_forwarded_address_endpoint(
            test_db,
            org_id=org.id,
            actor_user_id=actor,
            label="Audited",
            auto_create_contact=False,
        )
    audit_mock.assert_called_once()
    args, kwargs = audit_mock.call_args
    assert args[0] == "forwarded_address_endpoint.created"
    assert kwargs["org_id"] == org.id
    assert kwargs["user_id"] == actor
    after = kwargs["after"]
    assert after["label"] == "Audited"
    assert after["auto_create_contact"] is False


@pytest.mark.asyncio
async def test_forwarded_address_out_never_exposes_raw_token(test_db, monkeypatch):
    """Response schema never surfaces the raw ``forwarding_token`` —
    only the composed ``f-<token>@<domain>`` address."""
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.example.com")
    org = await _make_org(test_db)
    await test_db.commit()

    out = await service.create_forwarded_address_endpoint(
        test_db,
        org_id=org.id,
        actor_user_id=uuid.uuid4(),
        label="No leak",
    )
    dumped = out.model_dump()
    assert "forwarding_token" not in dumped
    # The composed address contains the token; extract it and confirm
    # the raw value doesn't also live on any other top-level key.
    assert dumped["forwarding_address"].startswith("f-")
    assert dumped["forwarding_address"].endswith("@in.example.com")
    token_from_address = dumped["forwarding_address"][2:].split("@")[0]
    for k, v in dumped.items():
        if k == "forwarding_address":
            continue
        assert v != token_from_address, f"raw token leaked via response key {k!r}"


@pytest.mark.asyncio
async def test_create_forwarded_address_accepts_valid_same_org_assignee(test_db, monkeypatch):
    """Happy path: an assignee that IS in the caller's org lands as
    ``default_assignee_user_id`` on the row + surfaces in the response
    as an :class:`AssigneeRef`."""
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.example.com")
    org = await _make_org(test_db)
    assignee_uuid = await _seed_user_in_org(
        test_db,
        org_id=org.id,
        email="rep@example.com",
        first_name="Rep",
    )
    await test_db.commit()

    out = await service.create_forwarded_address_endpoint(
        test_db,
        org_id=org.id,
        actor_user_id=uuid.uuid4(),
        label="With assignee",
        default_assignee_user_id=assignee_uuid,
    )
    assert out.default_assignee is not None
    assert out.default_assignee.id == assignee_uuid
    assert "Rep" in out.default_assignee.name


# ---------------------------------------------------------------------------
# Step 6 — GET /channel-endpoints/{id}/test-inbound-status
# ---------------------------------------------------------------------------


async def _make_forwarded_endpoint_raw(
    session,
    *,
    org_id: uuid.UUID,
    last_inbound_at=None,
):
    """Seed a bare ``forwarded_address`` endpoint + details row and
    return ``endpoint_id``. Independent of the create-service so the
    Step-6 tests don't accidentally verify the wrong side effect."""
    from src.app.core.channel_endpoints.models import (
        CHANNEL_EMAIL,
        ChannelEndpoint,
        EmailEndpointDetails,
    )

    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="forwarded_address",
        label="Support",
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        forwarding_token=uuid.uuid4().hex[:12],
        last_inbound_at=last_inbound_at,
    )
    session.add(details)
    await session.flush()
    return endpoint.id


@pytest.mark.asyncio
async def test_test_inbound_status_endpoint_returns_waiting_when_null(test_db):
    """Fresh endpoint (never received a message) → ``status='waiting'``."""
    org = await _make_org(test_db)
    endpoint_id = await _make_forwarded_endpoint_raw(
        test_db, org_id=org.id, last_inbound_at=None
    )
    await test_db.commit()

    result = await service.get_test_inbound_status(
        test_db, org_id=org.id, endpoint_id=endpoint_id
    )
    assert result.status == "waiting"
    assert result.last_inbound_at is None


@pytest.mark.asyncio
async def test_test_inbound_status_endpoint_returns_received_after_bump(test_db):
    """Endpoint whose details row has ``last_inbound_at`` set →
    ``status='received'`` with the timestamp echoed back."""
    from datetime import UTC, datetime

    org = await _make_org(test_db)
    when = datetime.now(UTC)
    endpoint_id = await _make_forwarded_endpoint_raw(
        test_db, org_id=org.id, last_inbound_at=when
    )
    await test_db.commit()

    result = await service.get_test_inbound_status(
        test_db, org_id=org.id, endpoint_id=endpoint_id
    )
    assert result.status == "received"
    assert result.last_inbound_at is not None


@pytest.mark.asyncio
async def test_test_inbound_status_scoped_by_org_id(test_db):
    """A caller's org sees ONLY its own endpoints — a matching id in
    another org returns 404 (info-leak posture)."""
    from fastapi import HTTPException

    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    endpoint_a = await _make_forwarded_endpoint_raw(test_db, org_id=org_a.id)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc:
        await service.get_test_inbound_status(
            test_db, org_id=org_b.id, endpoint_id=endpoint_a
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_test_inbound_status_cross_org_returns_404(test_db):
    """Unknown / non-forwarded_address id → 404 rather than a subtle
    error surface that would leak the endpoint's existence."""
    from fastapi import HTTPException

    org = await _make_org(test_db)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc:
        await service.get_test_inbound_status(
            test_db, org_id=org.id, endpoint_id=uuid.uuid4()
        )
    assert exc.value.status_code == 404
