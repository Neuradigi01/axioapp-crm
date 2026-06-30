"""Pin tests for Step-18 A/B testing utilities.

Covers:

  * Deterministic split: same `(contact_id, pair)` always picks the
    same variant.
  * 50/50 distribution over 1000 enrolments.
  * `pick_winner`: large positive lift → winner='b' with significant
    p-value.
  * `pick_winner`: marginal lift → winner='inconclusive'.
  * `pick_winner`: sample below `min_runs_per_variant` →
    winner='inconclusive'.
  * `auto_promote` archives loser + keeps existing runs.
  * `pair_for_ab` refuses if triggers differ.
  * `pair_for_ab` refuses if either side missing goal node.
  * `evaluate_pair_for_decision` extends holdback on inconclusive.
  * `evaluate_pair_for_decision` writes winner on decisive result.
  * `unpair_ab` stops the split (subsequent enrolments use primary).
  * `get_ab_stats` returns live rates with stable A/B labels.

Workflow rows are built via raw INSERTs through the model layer so
tests bypass the Step-2 graph validator (the focus here is split +
winner-picker correctness, not graph plumbing).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import ab_testing, service as workflows_service
from src.app.core.workflows.exceptions import InvalidGraph
from src.app.core.workflows.models import (
    ABWinnerMetric,
    Workflow,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


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
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _make_workflow(
    test_db,
    *,
    org_id,
    status: WorkflowStatus = WorkflowStatus.draft,
    enabled_event_types: list[str] | None = None,
    goal_node_id: str | None = "g1",
    name: str | None = None,
) -> Workflow:
    """Insert a workflow row directly. Bypasses validate_graph_with_db
    so A/B test fixtures can compose minimal rows."""
    wf = Workflow(
        org_id=org_id,
        name=name or f"WF-{uuid.uuid4().hex[:6]}",
        status=status,
        current_version=1,
        graph={"nodes": [], "edges": []},
        goal_node_id=goal_node_id,
        enabled_event_types=enabled_event_types or ["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _seed_runs(
    test_db, *, org_id, workflow_id, total: int, goal: int
) -> None:
    """Insert ``total`` runs against ``workflow_id`` with ``goal`` of
    them marked ``goal_reached``."""
    for i in range(total):
        outcome = (
            WorkflowRunOutcome.goal_reached
            if i < goal
            else WorkflowRunOutcome.completed
        )
        run = WorkflowRun(
            org_id=org_id,
            workflow_id=workflow_id,
            version=1,
            contact_id=None,
            status=WorkflowRunStatus.completed,
            outcome=outcome,
            current_node_id=None,
            state={},
        )
        test_db.add(run)
    await test_db.commit()


# ---------------------------------------------------------------------------
# Deterministic split
# ---------------------------------------------------------------------------


async def test_enroll_with_ab_split_is_deterministic_for_same_contact(
    test_db, org_id
):
    """Same `(contact_id, pair)` resolves to the same variant on
    every call — guarantees re-runs land consistently."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(test_db, org_id=org_id)
        b = await _make_workflow(test_db, org_id=org_id)
        a.ab_paired_workflow_id = b.id
        b.ab_paired_workflow_id = a.id
        await test_db.commit()
        await test_db.refresh(a)
        await test_db.refresh(b)
        cid = uuid.UUID("00000000-0000-0000-0000-000000000abc")
        first = await ab_testing.enroll_with_ab_split(
            test_db, workflow=a, contact_id=cid
        )
        second = await ab_testing.enroll_with_ab_split(
            test_db, workflow=a, contact_id=cid
        )
        third_from_b = await ab_testing.enroll_with_ab_split(
            test_db, workflow=b, contact_id=cid
        )
    finally:
        reset_context(token)

    assert first.id == second.id, "same contact must land on the same side"
    assert first.id == third_from_b.id, (
        "starting from the sibling must produce the same pick (pair-key invariant)"
    )


async def test_split_approximately_50_50_over_many_contacts(test_db, org_id):
    """Hash distribution should be near 50/50 over 1000 random
    contacts (allow up to ±10% slop for the sample size)."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(test_db, org_id=org_id)
        b = await _make_workflow(test_db, org_id=org_id)
        a.ab_paired_workflow_id = b.id
        b.ab_paired_workflow_id = a.id
        await test_db.commit()
        await test_db.refresh(a)
        a_count = 0
        b_count = 0
        for _ in range(1000):
            cid = uuid.uuid4()
            chosen = await ab_testing.enroll_with_ab_split(
                test_db, workflow=a, contact_id=cid
            )
            if chosen.id == a.id:
                a_count += 1
            else:
                b_count += 1
    finally:
        reset_context(token)

    # Split should be roughly half — accept 400..600 on each side.
    assert 400 <= a_count <= 600
    assert 400 <= b_count <= 600
    assert a_count + b_count == 1000


# ---------------------------------------------------------------------------
# pick_winner
# ---------------------------------------------------------------------------


async def test_pick_winner_returns_b_with_clear_lift(test_db, org_id):
    """200/1000 vs 300/1000 — a 50% relative lift; picker → 'b'."""
    a = await _make_workflow(test_db, org_id=org_id)
    b = await _make_workflow(test_db, org_id=org_id)
    await _seed_runs(test_db, org_id=org_id, workflow_id=a.id, total=1000, goal=200)
    await _seed_runs(test_db, org_id=org_id, workflow_id=b.id, total=1000, goal=300)
    result = await ab_testing.pick_winner(
        test_db,
        a_workflow_id=a.id,
        b_workflow_id=b.id,
        min_runs_per_variant=50,
    )
    assert result.winner == "b"
    assert result.p_value is not None and result.p_value < 0.05
    assert result.a_rate == pytest.approx(0.2)
    assert result.b_rate == pytest.approx(0.3)


async def test_pick_winner_inconclusive_on_marginal_lift(test_db, org_id):
    """50/100 vs 51/100 — well within noise; picker → 'inconclusive'."""
    a = await _make_workflow(test_db, org_id=org_id)
    b = await _make_workflow(test_db, org_id=org_id)
    await _seed_runs(test_db, org_id=org_id, workflow_id=a.id, total=100, goal=50)
    await _seed_runs(test_db, org_id=org_id, workflow_id=b.id, total=100, goal=51)
    result = await ab_testing.pick_winner(
        test_db,
        a_workflow_id=a.id,
        b_workflow_id=b.id,
        min_runs_per_variant=50,
    )
    assert result.winner == "inconclusive"


async def test_pick_winner_inconclusive_below_min_sample(test_db, org_id):
    """Sample below `min_runs_per_variant` is always inconclusive
    regardless of how decisive the rates look."""
    a = await _make_workflow(test_db, org_id=org_id)
    b = await _make_workflow(test_db, org_id=org_id)
    await _seed_runs(test_db, org_id=org_id, workflow_id=a.id, total=20, goal=0)
    await _seed_runs(test_db, org_id=org_id, workflow_id=b.id, total=20, goal=20)
    result = await ab_testing.pick_winner(
        test_db,
        a_workflow_id=a.id,
        b_workflow_id=b.id,
        min_runs_per_variant=50,
    )
    assert result.winner == "inconclusive"
    assert "insufficient sample" in result.reason


# ---------------------------------------------------------------------------
# auto_promote
# ---------------------------------------------------------------------------


async def test_auto_promote_archives_loser_and_activates_winner(test_db, org_id):
    a = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    b = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    # Pre-seed a "running" run on the loser so we can assert it is
    # NOT cancelled by auto-promote.
    in_flight = WorkflowRun(
        org_id=org_id,
        workflow_id=b.id,
        version=1,
        contact_id=None,
        status=WorkflowRunStatus.running,
        current_node_id="n1",
        state={},
    )
    test_db.add(in_flight)
    await test_db.commit()

    winner, loser = await ab_testing.auto_promote(
        test_db, winner_workflow_id=a.id, loser_workflow_id=b.id
    )
    await test_db.commit()
    await test_db.refresh(in_flight)

    assert winner.status == WorkflowStatus.active
    assert loser.status == WorkflowStatus.archived
    assert winner.ab_test_winner_workflow_id == a.id
    assert loser.ab_test_winner_workflow_id == a.id
    assert in_flight.status == WorkflowRunStatus.running, (
        "loser's in-flight runs must not be cancelled"
    )


# ---------------------------------------------------------------------------
# Service: pair_for_ab + unpair_ab + get_ab_stats
# ---------------------------------------------------------------------------


async def test_pair_for_ab_refuses_different_triggers(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(
            test_db, org_id=org_id, enabled_event_types=["lead.created"]
        )
        b = await _make_workflow(
            test_db, org_id=org_id, enabled_event_types=["quote.sent"]
        )
        with pytest.raises(InvalidGraph):
            await workflows_service.pair_for_ab(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=a.id,
                sibling_id=b.id,
                holdback_seconds=86400,
                metric="goal_conversion",
                min_runs_per_variant=50,
            )
    finally:
        reset_context(token)


async def test_pair_for_ab_refuses_missing_goal(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(test_db, org_id=org_id, goal_node_id=None)
        b = await _make_workflow(test_db, org_id=org_id, goal_node_id="g1")
        with pytest.raises(InvalidGraph):
            await workflows_service.pair_for_ab(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=a.id,
                sibling_id=b.id,
                holdback_seconds=86400,
                metric="goal_conversion",
                min_runs_per_variant=50,
            )
    finally:
        reset_context(token)


async def test_pair_then_unpair_clears_pairing(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(test_db, org_id=org_id)
        b = await _make_workflow(test_db, org_id=org_id)
        await workflows_service.pair_for_ab(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=a.id,
            sibling_id=b.id,
            holdback_seconds=86400,
            metric="goal_conversion",
            min_runs_per_variant=50,
        )
        await test_db.refresh(a)
        assert a.ab_paired_workflow_id == b.id
        assert a.status == WorkflowStatus.active

        unpaired = await workflows_service.unpair_ab(
            test_db, org_id=org_id, user_id=None, workflow_id=a.id
        )
    finally:
        reset_context(token)

    assert unpaired.ab_paired_workflow_id is None
    assert unpaired.ab_test_holdback_until is None
    assert unpaired.ab_test_started_at is None


# ---------------------------------------------------------------------------
# Beat-task decision pathway
# ---------------------------------------------------------------------------


async def test_evaluate_pair_extends_holdback_on_inconclusive(test_db, org_id):
    """Inconclusive pair → ab_test_holdback_until is bumped (no
    promotion)."""
    now = datetime.now(timezone.utc)
    a = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    b = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    # Pair manually + set holdback in the past so the beat task picks
    # them up.
    a.ab_paired_workflow_id = b.id
    b.ab_paired_workflow_id = a.id
    a.ab_test_started_at = now - timedelta(days=1)
    b.ab_test_started_at = now - timedelta(days=1)
    a.ab_test_holdback_until = now - timedelta(minutes=1)
    b.ab_test_holdback_until = now - timedelta(minutes=1)
    a.ab_test_min_runs_per_variant = 50
    b.ab_test_min_runs_per_variant = 50
    await test_db.commit()
    # Seed too few runs → inconclusive.
    await _seed_runs(test_db, org_id=org_id, workflow_id=a.id, total=10, goal=2)
    await _seed_runs(test_db, org_id=org_id, workflow_id=b.id, total=10, goal=3)

    primary = a if str(a.id) < str(b.id) else b
    outcome = await ab_testing.evaluate_pair_for_decision(
        test_db, workflow=primary, now=now
    )
    await test_db.commit()
    await test_db.refresh(a)
    await test_db.refresh(b)

    assert outcome["status"] == "extended"
    assert a.ab_test_decided_at is None
    assert b.ab_test_decided_at is None
    assert a.ab_test_holdback_until > now - timedelta(minutes=1)


async def test_evaluate_pair_decides_winner_on_clear_lift(test_db, org_id):
    """Decisive pair → winner activated, loser archived, decided_at
    stamped."""
    now = datetime.now(timezone.utc)
    a = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    b = await _make_workflow(test_db, org_id=org_id, status=WorkflowStatus.active)
    a.ab_paired_workflow_id = b.id
    b.ab_paired_workflow_id = a.id
    a.ab_test_started_at = now - timedelta(days=1)
    b.ab_test_started_at = now - timedelta(days=1)
    a.ab_test_holdback_until = now - timedelta(minutes=1)
    b.ab_test_holdback_until = now - timedelta(minutes=1)
    a.ab_test_min_runs_per_variant = 50
    b.ab_test_min_runs_per_variant = 50
    await test_db.commit()

    # Make whoever sorts first (= variant A) clearly worse so the
    # decision is unambiguous.
    a_workflow, b_workflow = (a, b) if str(a.id) < str(b.id) else (b, a)
    await _seed_runs(
        test_db, org_id=org_id, workflow_id=a_workflow.id, total=1000, goal=100
    )
    await _seed_runs(
        test_db, org_id=org_id, workflow_id=b_workflow.id, total=1000, goal=400
    )

    primary = a if str(a.id) < str(b.id) else b
    outcome = await ab_testing.evaluate_pair_for_decision(
        test_db, workflow=primary, now=now
    )
    await test_db.commit()
    await test_db.refresh(a_workflow)
    await test_db.refresh(b_workflow)

    assert outcome["status"] == "decided"
    assert outcome["winner_workflow_id"] == str(b_workflow.id)
    assert b_workflow.status == WorkflowStatus.active
    assert a_workflow.status == WorkflowStatus.archived
    assert b_workflow.ab_test_decided_at is not None
    assert a_workflow.ab_test_decided_at is not None


# ---------------------------------------------------------------------------
# get_ab_stats
# ---------------------------------------------------------------------------


async def test_get_ab_stats_returns_live_rates(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        a = await _make_workflow(test_db, org_id=org_id)
        b = await _make_workflow(test_db, org_id=org_id)
        await workflows_service.pair_for_ab(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=a.id,
            sibling_id=b.id,
            holdback_seconds=86400,
            metric="goal_conversion",
            min_runs_per_variant=50,
        )
        a_workflow, b_workflow = (a, b) if str(a.id) < str(b.id) else (b, a)
        await _seed_runs(
            test_db, org_id=org_id, workflow_id=a_workflow.id, total=200, goal=40
        )
        await _seed_runs(
            test_db, org_id=org_id, workflow_id=b_workflow.id, total=200, goal=80
        )
        stats = await workflows_service.get_ab_stats(
            test_db, org_id=org_id, workflow_id=a.id
        )
    finally:
        reset_context(token)

    assert stats["a_workflow_id"] == a_workflow.id
    assert stats["b_workflow_id"] == b_workflow.id
    assert stats["a_total_runs"] == 200
    assert stats["b_total_runs"] == 200
    assert stats["a_rate"] == pytest.approx(0.2)
    assert stats["b_rate"] == pytest.approx(0.4)
    assert stats["winner"] in {"a", "b", "inconclusive"}
