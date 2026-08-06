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
    """The node config carries an explicit user_id — resolver joins
    ``tbl_user_login`` (via ``legacy_uuid``) to ``tbl_user_info``
    where email actually lives (email is a Python ``@property`` on
    ``User``, not a mapped column)."""
    user_uuid = await _make_user(test_db, email="owner@example.com")
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


# ---------------------------------------------------------------------------
# String-form recipient config — the UI writes `recipient: "lead.owner"` as a
# plain string (not the dict `{"kind": ..., "method": ...}` form). Every
# resolver that reads params from `config.recipient` must handle both shapes
# without crashing on `.get(...)` against a str.
# ---------------------------------------------------------------------------


async def test_contact_email_string_recipient_form(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id, email="s@example.com", phone=None)
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"config": {"recipient": "contact.email"}}
    result = await resolve("contact.email", test_db, run=run, node=node, context={})
    assert result == "s@example.com"


async def test_custom_string_recipient_form_returns_none(test_db, org_id):
    """String-form ``recipient: "custom"`` has no ``path`` param —
    the resolver must return ``None`` (skip), not crash."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": "custom"}}
    context = {"trigger_payload": {"foo": "bar"}}
    result = await resolve("custom", test_db, run=run, node=node, context=context)
    assert result is None


async def test_lead_owner_string_recipient_form_no_lead_returns_none(test_db, org_id):
    """String-form ``recipient: "lead.owner"`` on a run with no lead
    in payload and no contact — resolver must return None, not crash
    with ``'str' object has no attribute 'get'``."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": "lead.owner"}}
    result = await resolve(
        "lead.owner", test_db, run=run, node=node, context={"trigger_payload": {}}
    )
    assert result is None


# ---------------------------------------------------------------------------
# lead.owner — schedule-fire fallback via run.contact_id
# ---------------------------------------------------------------------------


async def _make_user(test_db, *, email: str) -> uuid.UUID:
    """Seed a user across the split ``tbl_user_login`` (auth) +
    ``tbl_user_info`` (profile) tables. Email lives on the info
    row — the login row only carries auth material."""
    user_uuid = uuid.uuid4()
    result = await test_db.execute(
        sql_text(
            "INSERT INTO tbl_user_login (legacy_uuid, password, is_active) "
            "VALUES (:uuid, :pw, true) RETURNING id"
        ),
        {"uuid": str(user_uuid), "pw": "x"},
    )
    member_id = result.scalar_one()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_user_info (member_id, first_name, last_name, email) "
            "VALUES (:mid, :fn, :ln, :email)"
        ),
        {"mid": member_id, "fn": "Test", "ln": "User", "email": email},
    )
    await test_db.commit()
    return user_uuid


async def _make_lead(
    test_db,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
) -> uuid.UUID:
    lead_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_leads (id, org_id, contact_id, pipeline_stage, assigned_to_id) "
            "VALUES (:id, :org_id, :contact_id, 'new', :assigned_to_id)"
        ),
        {
            "id": str(lead_id),
            "org_id": str(org_id),
            "contact_id": str(contact_id),
            "assigned_to_id": str(assigned_to_id) if assigned_to_id else None,
        },
    )
    await test_db.commit()
    return lead_id


async def test_lead_owner_string_form_falls_back_to_contact_lead(test_db, org_id):
    """Schedule-triggered run scenario: no lead in trigger_payload,
    but the schedule was bound to a contact_id. The resolver must
    look up the contact's most-recent assigned lead + return that
    owner's email."""
    owner_uuid = await _make_user(test_db, email="owner@example.com")
    contact_id = await _make_contact(test_db, org_id=org_id, email=None, phone=None)
    await _make_lead(test_db, org_id=org_id, contact_id=contact_id, assigned_to_id=owner_uuid)

    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"config": {"recipient": "lead.owner"}}
    context = {"trigger_payload": {"schedule_id": str(uuid.uuid4())}}

    result = await resolve("lead.owner", test_db, run=run, node=node, context=context)
    assert result == "owner@example.com"


async def test_custom_string_form_reads_recipient_custom_literal_email(test_db, org_id):
    """UI "Custom path…" writes ``config.recipient = "custom"`` plus
    ``config.recipient_custom = "dev@example.com"`` — the resolver
    must pick up the literal email from the sibling field."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": "custom", "recipient_custom": "dev@example.com"}}
    result = await resolve("custom", test_db, run=run, node=node, context={"trigger_payload": {}})
    assert result == "dev@example.com"


async def test_custom_string_form_reads_recipient_custom_dotted_path(test_db, org_id):
    """Same UI path but with a dotted path — should walk the trigger
    payload as before."""
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=None)
    node = {"config": {"recipient": "custom", "recipient_custom": "contact.alt_email"}}
    context = {"trigger_payload": {"contact": {"alt_email": "alt@example.com"}}}
    result = await resolve("custom", test_db, run=run, node=node, context=context)
    assert result == "alt@example.com"


async def test_lead_owner_contact_fallback_skips_unassigned_leads(test_db, org_id):
    """A contact with 2 leads (one unassigned, one assigned) should
    resolve to the assigned one — the unassigned lead must not
    poison the lookup."""
    owner_uuid = await _make_user(test_db, email="assigned@example.com")
    contact_id = await _make_contact(test_db, org_id=org_id, email=None, phone=None)
    await _make_lead(test_db, org_id=org_id, contact_id=contact_id, assigned_to_id=None)
    await _make_lead(test_db, org_id=org_id, contact_id=contact_id, assigned_to_id=owner_uuid)

    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"config": {"recipient": {"kind": "lead.owner", "method": "email"}}}
    result = await resolve("lead.owner", test_db, run=run, node=node, context={})
    assert result == "assigned@example.com"
