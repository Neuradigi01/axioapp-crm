"""Pin tests for the Step-7 recipient resolver registry.

Covers the four built-in resolvers + the registry's
``UnknownResolver`` error path + the custom-resolver depth + length
caps.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows.recipients import (
    UnknownResolver,
    resolve,
)

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    """Minimal stand-in for a WorkflowRun — the resolvers only read
    ``org_id``, ``workflow_id``, and ``contact_id`` so a dataclass
    is enough for the recipient-only tests."""

    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _make_contact(test_db, *, org_id, email: str | None, phone: str | None) -> uuid.UUID:
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, email, phone) "
            "VALUES (:id, :org_id, :name, :email, :phone)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "name": "Asha Mehta",
            "email": email,
            "phone": phone,
        },
    )
    await test_db.commit()
    return contact_id


# ---------------------------------------------------------------------------
# contact.email / contact.phone
# ---------------------------------------------------------------------------


async def test_contact_email_from_context_dict(test_db, org_id):
    """Hot path — the engine pre-hydrates the contact dict into the
    context so the resolver doesn't need a DB round-trip."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"email": "asha@example.com"},
        "trigger_payload": {},
        "run_state": {},
    }
    result = await resolve("contact.email", test_db, run=run, node={"config": {}}, context=context)
    assert result == "asha@example.com"


async def test_contact_email_fallback_to_db(test_db, org_id):
    """When the context dict lacks email but run.contact_id is set,
    the resolver falls back to a direct DB lookup."""
    contact_id = await _make_contact(test_db, org_id=org_id, email="db@example.com", phone=None)
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    context = {"contact": None, "trigger_payload": {}, "run_state": {}}
    result = await resolve("contact.email", test_db, run=run, node={"config": {}}, context=context)
    assert result == "db@example.com"


async def test_contact_email_returns_none_when_missing(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id, email=None, phone=None)
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    context = {"contact": {}, "trigger_payload": {}, "run_state": {}}
    result = await resolve("contact.email", test_db, run=run, node={"config": {}}, context=context)
    assert result is None


async def test_contact_phone_from_context(test_db, org_id):
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "contact": {"phone": "+919876543210"},
        "trigger_payload": {},
        "run_state": {},
    }
    result = await resolve("contact.phone", test_db, run=run, node={"config": {}}, context=context)
    assert result == "+919876543210"


# ---------------------------------------------------------------------------
# user.email
# ---------------------------------------------------------------------------


async def test_user_email_via_node_config(test_db, org_id):
    """The node config carries an explicit user_id — resolver hits
    tbl_user_login via the User model's legacy_uuid column."""
    user_uuid = uuid.uuid4()
    # Seed a minimal user row. We use raw SQL because the User
    # model has cascading FK relationships that the conftest may
    # not set up fully for an isolated recipient test.
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_user_login "
            "(legacy_uuid, email, password_hash, is_active, full_name) "
            "VALUES (:uuid, :email, :hash, true, :name)"
        ),
        {
            "uuid": str(user_uuid),
            "email": "owner@example.com",
            "hash": "x",
            "name": "Owner",
        },
    )
    await test_db.commit()

    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": {"kind": "user.email", "user_id": str(user_uuid)}}}
    result = await resolve("user.email", test_db, run=run, node=node, context={})
    assert result == "owner@example.com"


# ---------------------------------------------------------------------------
# custom — dot-path
# ---------------------------------------------------------------------------


async def test_custom_resolver_walks_dot_path(test_db, org_id):
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    context = {
        "trigger_payload": {
            "contact": {"alt_email": "alt@example.com"},
        },
    }
    node = {"config": {"recipient": {"kind": "custom", "path": "contact.alt_email"}}}
    result = await resolve("custom", test_db, run=run, node=node, context=context)
    assert result == "alt@example.com"


async def test_custom_resolver_depth_cap_returns_none(test_db, org_id):
    """A path with more than 10 segments is rejected."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    long_path = ".".join([f"seg{i}" for i in range(15)])
    node = {"config": {"recipient": {"kind": "custom", "path": long_path}}}
    context = {"trigger_payload": {}}
    result = await resolve("custom", test_db, run=run, node=node, context=context)
    assert result is None


async def test_custom_resolver_missing_path_returns_none(test_db, org_id):
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": {"kind": "custom", "path": "no.such.key"}}}
    context = {"trigger_payload": {"contact": {"email": "asha@x.com"}}}
    result = await resolve("custom", test_db, run=run, node=node, context=context)
    assert result is None


# ---------------------------------------------------------------------------
# Unknown resolver
# ---------------------------------------------------------------------------


async def test_unknown_resolver_raises(test_db, org_id):
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    with pytest.raises(UnknownResolver) as exc:
        await resolve(
            "nope.does_not_exist",
            test_db,
            run=run,
            node={"config": {}},
            context={},
        )
    assert exc.value.name == "nope.does_not_exist"
