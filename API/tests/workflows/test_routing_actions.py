"""Pin tests for the Step-9 routing action handlers.

Exercises the five routing modes against seeded org data. The
``reassign_lead`` / ``reassign_contact`` paths require the test
DB to have real User + OrganizationMember + Role rows; the
fixtures here build a 3-rep "Sales" pool so the round-robin +
least-loaded paths can be observed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
    resolve as resolve_action,
)
from src.app.core.workflows.actions import routing as routing_module
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_by_user_id: uuid.UUID | None = None


@dataclass
class _FakeStepRun:
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest_asyncio.fixture
async def org_with_settings(test_db):
    """Seed an org + its OrgSettings row so the routing pointer
    bump can SELECT FOR UPDATE against it."""
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_org_settings (id, org_id) "
            "VALUES (:id, :org_id)"
        ),
        {"id": str(uuid.uuid4()), "org_id": str(org_id)},
    )
    await test_db.commit()
    return org_id


async def _seed_user(test_db, *, email: str) -> uuid.UUID:
    """Create a tbl_user_login + tbl_user_info row + return the
    legacy_uuid (the UUID identity routing helpers traffic in)."""
    user_uuid = uuid.uuid4()
    login_id_row = await test_db.execute(
        sql_text(
            "INSERT INTO tbl_user_login "
            "(legacy_uuid, password_hash, is_active, full_name) "
            "VALUES (:uuid, :hash, true, :name) RETURNING id"
        ),
        {"uuid": str(user_uuid), "hash": "x", "name": "User"},
    )
    _ = login_id_row.scalar_one()
    await test_db.commit()
    return user_uuid


async def _seed_role(test_db, *, org_id, name: str) -> uuid.UUID:
    role_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_roles "
            "(id, organization_id, name, is_system, source) "
            "VALUES (:id, :org_id, :name, false, 'user')"
        ),
        {"id": str(role_id), "org_id": str(org_id), "name": name},
    )
    await test_db.commit()
    return role_id


async def _seed_membership(test_db, *, org_id, user_uuid, role_id) -> None:
    # Find the bigint user id by legacy_uuid + insert membership.
    user_id = (
        await test_db.execute(
            sql_text(
                "SELECT id FROM tbl_user_login WHERE legacy_uuid = :uuid"
            ),
            {"uuid": str(user_uuid)},
        )
    ).scalar_one()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organization_members "
            "(organization_id, user_member_id, role_id, status, is_active, is_demo) "
            "VALUES (:org_id, :user_id, :role_id, 'active', true, false)"
        ),
        {
            "org_id": str(org_id),
            "user_id": user_id,
            "role_id": str(role_id),
        },
    )
    await test_db.commit()


async def _seed_sales_pool(test_db, *, org_id) -> tuple[list[uuid.UUID], uuid.UUID]:
    """Seed 3 sales reps in role 'Sales'. Returns (user_uuids, role_id)
    with user_uuids sorted ascending to match the routing helper's
    internal sort order."""
    role_id = await _seed_role(test_db, org_id=org_id, name="Sales")
    users = []
    for label in ("a-asha", "b-rahul", "c-priya"):
        u = await _seed_user(test_db, email=f"{label}@example.com")
        await _seed_membership(
            test_db, org_id=org_id, user_uuid=u, role_id=role_id
        )
        users.append(u)
    # Sort by str(uuid) — matches `_bump_routing_pointer`'s sort.
    users.sort(key=str)
    return users, role_id


async def _seed_lead(test_db, *, org_id, contact_id=None) -> Lead:
    if contact_id is None:
        contact_id = uuid.uuid4()
        await test_db.execute(
            sql_text(
                "INSERT INTO tbl_contacts (id, org_id, full_name) "
                "VALUES (:id, :org_id, :name)"
            ),
            {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
        )
        await test_db.commit()
    lead = Lead(
        org_id=org_id,
        contact_id=contact_id,
        status=LeadStatus.active,
        pipeline_stage="new",
        source="manual",
    )
    test_db.add(lead)
    await test_db.commit()
    await test_db.refresh(lead)
    return lead


@pytest.fixture(autouse=True)
def _reset_action_registry():
    _clear_registry_for_tests()
    _register_builtins()
    routing_module.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()
    routing_module.register()


def _run_for(org_id, contact_id=None) -> _FakeRun:
    return _FakeRun(
        org_id=org_id,
        workflow_id=uuid.uuid4(),
        contact_id=contact_id,
        created_by_user_id=None,
    )


# ---------------------------------------------------------------------------
# routing.round_robin — cycle order + persisted pointer
# ---------------------------------------------------------------------------


async def test_round_robin_cycles_through_pool(test_db, org_with_settings):
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)

    # Three round-robin fires, each with a fresh lead.
    picks = []
    for _ in range(3):
        lead = await _seed_lead(test_db, org_id=org_id)
        run = _run_for(org_id, contact_id=lead.contact_id)
        handler = resolve_action("routing.round_robin")
        node = {
            "id": "rr",
            "type": "routing.round_robin",
            "config": {
                "pool": "role:Sales",
                "target": "lead.assigned_to_id",
                "lead_id": str(lead.id),
            },
        }
        token = set_context(RequestContext(org_id=org_id))
        try:
            result = await handler(
                test_db,
                run=run,
                step_run=_FakeStepRun(),
                node=node,
                context={"trigger_payload": {}, "run_state": {}, "contact": None},
            )
        finally:
            reset_context(token)
        assert result.skip_reason is None, result.output
        picks.append(uuid.UUID(result.output["assigned_user_id"]))

    # All three reps got exactly one assignment.
    assert sorted(picks, key=str) == users


async def test_round_robin_single_user_pool(test_db, org_with_settings):
    org_id = org_with_settings
    role_id = await _seed_role(test_db, org_id=org_id, name="Solo")
    only_user = await _seed_user(test_db, email="solo@example.com")
    await _seed_membership(
        test_db, org_id=org_id, user_uuid=only_user, role_id=role_id
    )

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.round_robin")
    node = {
        "id": "rr",
        "type": "routing.round_robin",
        "config": {
            "pool": "role:Solo",
            "target": "lead.assigned_to_id",
            "lead_id": str(lead.id),
        },
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert uuid.UUID(result.output["assigned_user_id"]) == only_user


async def test_round_robin_empty_pool_skips(test_db, org_with_settings):
    org_id = org_with_settings
    # No role 'Sales' exists in this org → empty pool.
    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.round_robin")
    node = {
        "id": "rr",
        "type": "routing.round_robin",
        "config": {
            "pool": "role:Sales",
            "target": "lead.assigned_to_id",
            "lead_id": str(lead.id),
        },
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "no_candidates"
    assert result.output["pool_size"] == 0


# ---------------------------------------------------------------------------
# routing.least_loaded
# ---------------------------------------------------------------------------


async def test_least_loaded_picks_user_with_fewest_open_leads(
    test_db, org_with_settings
):
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    asha, rahul, priya = users

    # Asha has 3 open leads, Rahul has 1, Priya has 0 → Priya wins.
    for u, count in ((asha, 3), (rahul, 1), (priya, 0)):
        for _ in range(count):
            seeded = await _seed_lead(test_db, org_id=org_id)
            seeded.assigned_to_id = u
            await test_db.commit()

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.least_loaded")
    node = {
        "id": "ll",
        "type": "routing.least_loaded",
        "config": {
            "pool": "role:Sales",
            "target": "lead.assigned_to_id",
            "lead_id": str(lead.id),
        },
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert uuid.UUID(result.output["assigned_user_id"]) == priya


# ---------------------------------------------------------------------------
# routing.territory
# ---------------------------------------------------------------------------


async def test_territory_matches_by_region(test_db, org_with_settings):
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    asha, rahul, priya = users

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.territory")
    node = {
        "id": "tr",
        "type": "routing.territory",
        "config": {
            "match_field": "region",
            "territory_map": {
                str(asha): ["delhi", "mumbai"],
                str(rahul): ["bangalore"],
            },
            "fallback": "round_robin",
            "pool": "role:Sales",
            "lead_id": str(lead.id),
            "target": "lead.assigned_to_id",
        },
    }
    context = {
        "trigger_payload": {"lead": {"region": "Mumbai"}},
        "run_state": {},
        "contact": None,
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert uuid.UUID(result.output["assigned_user_id"]) == asha
    assert result.output["assignment_method"] == "territory"


async def test_territory_falls_through_to_round_robin(
    test_db, org_with_settings
):
    """No territory map entry matches 'pune' → fallback round_robin."""
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    asha, rahul, priya = users

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.territory")
    node = {
        "id": "tr",
        "type": "routing.territory",
        "config": {
            "match_field": "region",
            "territory_map": {str(asha): ["delhi"]},
            "fallback": "round_robin",
            "pool": "role:Sales",
            "lead_id": str(lead.id),
            "target": "lead.assigned_to_id",
        },
    }
    context = {
        "trigger_payload": {"lead": {"region": "pune"}},
        "run_state": {},
        "contact": None,
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert result.output["assignment_method"] == "round_robin"


# ---------------------------------------------------------------------------
# routing.skill
# ---------------------------------------------------------------------------


async def test_skill_matches_by_skill_required(test_db, org_with_settings):
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    asha, rahul, priya = users

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.skill")
    node = {
        "id": "sk",
        "type": "routing.skill",
        "config": {
            "match_field": "skill_required",
            "skill_map": {str(rahul): ["enterprise", "SaaS"]},
            "fallback": "round_robin",
            "pool": "role:Sales",
            "lead_id": str(lead.id),
            "target": "lead.assigned_to_id",
        },
    }
    context = {
        "trigger_payload": {"lead": {"skill_required": "SaaS"}},
        "run_state": {},
        "contact": None,
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert uuid.UUID(result.output["assigned_user_id"]) == rahul


# ---------------------------------------------------------------------------
# routing.specific_user
# ---------------------------------------------------------------------------


async def test_specific_user_assigns_to_configured_uuid(
    test_db, org_with_settings
):
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    target_user = users[1]

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.specific_user")
    node = {
        "id": "su",
        "type": "routing.specific_user",
        "config": {
            "user_id": str(target_user),
            "lead_id": str(lead.id),
            "target": "lead.assigned_to_id",
        },
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    assert uuid.UUID(result.output["assigned_user_id"]) == target_user
    assert result.output["pool_size"] == 1


async def test_specific_user_missing_user_id_validation_failed(
    test_db, org_with_settings
):
    org_id = org_with_settings
    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.specific_user")
    node = {
        "id": "su",
        "type": "routing.specific_user",
        "config": {"lead_id": str(lead.id), "target": "lead.assigned_to_id"},
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "validation_failed"


# ---------------------------------------------------------------------------
# Assignment writes a timeline activity row
# ---------------------------------------------------------------------------


async def test_assignment_writes_timeline_activity(
    test_db, org_with_settings
):
    """The reassign helper writes an ``Activity(type=reassign)`` row;
    the routing wrapper passes the workflow-author note. Asserts the
    timeline got the entry."""
    org_id = org_with_settings
    users, _ = await _seed_sales_pool(test_db, org_id=org_id)
    target_user = users[0]

    lead = await _seed_lead(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=lead.contact_id)
    handler = resolve_action("routing.specific_user")
    node = {
        "id": "su",
        "type": "routing.specific_user",
        "config": {
            "user_id": str(target_user),
            "lead_id": str(lead.id),
            "target": "lead.assigned_to_id",
        },
    }

    token = set_context(RequestContext(org_id=org_id))
    try:
        await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)

    # Inspect tbl_activities for the reassign row.
    rows = (
        await test_db.execute(
            sql_text(
                "SELECT type, payload FROM tbl_activities "
                "WHERE org_id = :org_id "
                "AND entity_type = 'lead' AND entity_id = :lead_id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"org_id": str(org_id), "lead_id": str(lead.id)},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == "reassign"
