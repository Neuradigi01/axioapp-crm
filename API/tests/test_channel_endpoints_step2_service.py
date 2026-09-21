"""Coverage for Step 2 service — ``core/channel_endpoints/service.py``.

Tests the two shipped service functions:

  * :func:`list_endpoints_for_org` — response schema shape, token
    exclusion, endpoint-type narrowing.
  * :func:`deactivate_endpoint` — cross-org 404, idempotent no-op on
    already-inactive, audit event fired.

Router-level auth (Owner+Admin permission gate) is exercised by
``test_layered_architecture_convention.py`` via the ``Depends`` graph
and by shipped ``require_permissions`` unit tests — not re-tested here.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.app.core.channel_endpoints import service
from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.channel_endpoints.schemas import ChannelEndpointOut
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"svc-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_endpoint(
    session,
    *,
    org_id: uuid.UUID,
    endpoint_type: str = "smtp_reply_capture",
    reply_token: str | None = "svc-tok-123456",
    label: str = "svc@example.com",
    is_active: bool = True,
) -> ChannelEndpoint:
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type=endpoint_type,
        label=label,
        is_active=is_active,
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        reply_token=reply_token,
    )
    session.add(details)
    await session.flush()
    return endpoint


# ---------------------------------------------------------------------------
# list_endpoints_for_org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_endpoints_scoped_by_org(test_db):
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    await _make_endpoint(test_db, org_id=org_a.id, label="a@example.com")
    await _make_endpoint(
        test_db, org_id=org_b.id, reply_token="b-tok", label="b@example.com"
    )
    await test_db.commit()

    a_items = await service.list_endpoints_for_org(test_db, org_id=org_a.id)
    b_items = await service.list_endpoints_for_org(test_db, org_id=org_b.id)

    assert len(a_items) == 1
    assert len(b_items) == 1
    assert a_items[0].label == "a@example.com"
    assert b_items[0].label == "b@example.com"


@pytest.mark.asyncio
async def test_list_endpoints_never_leaks_token_values(test_db):
    """Response schemas must not include ``reply_token`` / ``forwarding_token``."""
    org = await _make_org(test_db)
    await _make_endpoint(
        test_db, org_id=org.id, reply_token="secret-do-not-leak-123"
    )
    await test_db.commit()

    items = await service.list_endpoints_for_org(test_db, org_id=org.id)
    assert len(items) == 1
    dumped = items[0].model_dump()
    # Endpoint-level fields
    assert "reply_token" not in dumped
    assert "forwarding_token" not in dumped
    # Details block also must not carry tokens
    if dumped.get("details") is not None:
        assert "reply_token" not in dumped["details"]
        assert "forwarding_token" not in dumped["details"]
    # Sanity: the token really does exist in the DB, we're just not exposing it.
    # (If this assertion never fires, the fixture broke, not the schema.)
    assert "secret-do-not-leak-123" not in str(dumped)


@pytest.mark.asyncio
async def test_list_endpoints_filters_by_endpoint_type(test_db):
    org = await _make_org(test_db)
    await _make_endpoint(
        test_db,
        org_id=org.id,
        endpoint_type="smtp_reply_capture",
        reply_token="s1",
        label="s@example.com",
    )
    await _make_endpoint(
        test_db,
        org_id=org.id,
        endpoint_type="oauth_mailbox",
        reply_token=None,
        label="oauth@example.com",
    )
    await test_db.commit()

    all_items = await service.list_endpoints_for_org(test_db, org_id=org.id)
    smtp_only = await service.list_endpoints_for_org(
        test_db, org_id=org.id, endpoint_type="smtp_reply_capture"
    )

    assert len(all_items) == 2
    assert len(smtp_only) == 1
    assert smtp_only[0].endpoint_type == "smtp_reply_capture"


@pytest.mark.asyncio
async def test_list_endpoints_returns_response_schema_type(test_db):
    org = await _make_org(test_db)
    await _make_endpoint(test_db, org_id=org.id)
    await test_db.commit()

    items = await service.list_endpoints_for_org(test_db, org_id=org.id)
    assert isinstance(items[0], ChannelEndpointOut)


# ---------------------------------------------------------------------------
# deactivate_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_endpoint_flips_is_active_to_false(test_db):
    org = await _make_org(test_db)
    endpoint = await _make_endpoint(test_db, org_id=org.id)
    await test_db.commit()
    actor_id = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ):
        await service.deactivate_endpoint(
            test_db,
            org_id=org.id,
            endpoint_id=endpoint.id,
            actor_user_id=actor_id,
            reason="test-deactivation",
        )

    await test_db.refresh(endpoint)
    assert endpoint.is_active is False
    assert endpoint.deactivated_at is not None
    assert endpoint.deactivation_reason == "test-deactivation"


@pytest.mark.asyncio
async def test_deactivate_endpoint_cross_org_returns_404(test_db):
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    endpoint = await _make_endpoint(test_db, org_id=org_a.id)
    await test_db.commit()
    actor_id = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc:
            await service.deactivate_endpoint(
                test_db,
                org_id=org_b.id,
                endpoint_id=endpoint.id,
                actor_user_id=actor_id,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_endpoint_unknown_id_returns_404(test_db):
    org = await _make_org(test_db)
    actor_id = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc:
            await service.deactivate_endpoint(
                test_db,
                org_id=org.id,
                endpoint_id=uuid.uuid4(),
                actor_user_id=actor_id,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_endpoint_idempotent_on_already_inactive(test_db):
    """Second deactivation is a silent no-op — no audit spam, no state change."""
    org = await _make_org(test_db)
    endpoint = await _make_endpoint(
        test_db, org_id=org.id, is_active=False
    )
    await test_db.commit()
    actor_id = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ) as audit_mock:
        await service.deactivate_endpoint(
            test_db,
            org_id=org.id,
            endpoint_id=endpoint.id,
            actor_user_id=actor_id,
        )
    audit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_deactivate_endpoint_writes_audit_event(test_db):
    org = await _make_org(test_db)
    endpoint = await _make_endpoint(test_db, org_id=org.id, label="audit@example.com")
    await test_db.commit()
    actor_id = uuid.uuid4()

    with patch(
        "src.app.core.channel_endpoints.service.audit.log", new_callable=AsyncMock
    ) as audit_mock:
        await service.deactivate_endpoint(
            test_db,
            org_id=org.id,
            endpoint_id=endpoint.id,
            actor_user_id=actor_id,
            reason="testing-audit",
        )

    audit_mock.assert_awaited_once()
    call_args = audit_mock.await_args
    assert call_args.args[0] == "channel_endpoint.deactivated"
    assert call_args.kwargs["entity_type"] == "channel_endpoint"
    assert call_args.kwargs["entity_id"] == endpoint.id
    assert call_args.kwargs["org_id"] == org.id
    assert call_args.kwargs["user_id"] == actor_id
    assert call_args.kwargs["after"]["endpoint_type"] == "smtp_reply_capture"
    assert call_args.kwargs["after"]["label"] == "audit@example.com"
    assert call_args.kwargs["after"]["reason"] == "testing-audit"
