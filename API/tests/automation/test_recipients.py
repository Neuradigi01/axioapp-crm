"""Pin tests for the Step-2 recipient resolver registry.

Each resolver is tested both for the "payload carries the
denormalised dict" happy path (no DB hit) and the "payload only
carries the id" fallback path (resolver issues the DB lookup).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text as sql_text

from src.app.core.automation import recipients

pytestmark = pytest.mark.asyncio


# --- happy paths (payload carries the dict; no DB call) ----------


async def test_contact_email_from_payload_dict():
    addr = await recipients.resolve(
        "contact.email",
        session=AsyncMock(),
        payload={"contact": {"email": "asha@example.com"}},
    )
    assert addr == "asha@example.com"


async def test_contact_phone_from_payload_dict():
    addr = await recipients.resolve(
        "contact.phone",
        session=AsyncMock(),
        payload={"contact": {"phone": "+919876543210"}},
    )
    assert addr == "+919876543210"


async def test_user_email_from_payload_dict():
    addr = await recipients.resolve(
        "user.email",
        session=AsyncMock(),
        payload={"user": {"email": "owner@org.example"}},
    )
    assert addr == "owner@org.example"


async def test_custom_resolver_walks_dotpath():
    addr = await recipients.resolve(
        "custom",
        session=AsyncMock(),
        payload={"deal": {"owner_email": "owner@org.example"}},
        config={"path": "deal.owner_email"},
    )
    assert addr == "owner@org.example"


# --- fallback paths (only id present; resolver looks up) ----------


async def test_contact_email_fallback_to_db_lookup(test_db):
    # Insert a contact + org and resolve via contact_id only.
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, email, first_name) "
            "VALUES (:id, :org_id, :email, :first_name)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "email": "lookup@example.com",
            "first_name": "Lookup",
        },
    )
    await test_db.commit()
    addr = await recipients.resolve(
        "contact.email",
        session=test_db,
        payload={"contact_id": str(contact_id)},
    )
    assert addr == "lookup@example.com"


# --- missing data returns None ------------------------------------


async def test_contact_email_returns_none_when_missing():
    addr = await recipients.resolve(
        "contact.email",
        session=AsyncMock(),
        payload={},  # no contact + no contact_id
    )
    assert addr is None


async def test_custom_resolver_returns_none_when_path_missing():
    addr = await recipients.resolve(
        "custom",
        session=AsyncMock(),
        payload={"deal": {"id": "..."}},
        config={"path": "deal.owner_email"},
    )
    assert addr is None


async def test_custom_resolver_returns_none_without_config_path():
    addr = await recipients.resolve(
        "custom",
        session=AsyncMock(),
        payload={"x": "y"},
        config={},
    )
    assert addr is None


# --- registry behaviour ------------------------------------------


async def test_unknown_resolver_raises():
    with pytest.raises(recipients.UnknownResolver):
        await recipients.resolve(
            "nope",
            session=AsyncMock(),
            payload={},
        )


async def test_register_resolver_is_idempotent():
    """Re-registering the same (name, fn) pair must not crash —
    side-effect imports may re-run."""

    async def fake(_session, _payload, _config):
        return "x@y.com"

    recipients.register_resolver("test.fake", fake)
    recipients.register_resolver("test.fake", fake)
    addr = await recipients.resolve("test.fake", session=AsyncMock(), payload={})
    assert addr == "x@y.com"
