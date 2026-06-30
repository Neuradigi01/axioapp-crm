"""Pin tests for Step-19 workflow analytics.

Covers:

  * Headline counters (enrolled / completed / goal_reached / errored
    / running) from seeded run rows.
  * Conversion rate = goal_reached / enrolled.
  * Funnel returns one row per node_id with status counts.
  * Skip-reason breakdown per step.
  * Daily-rate aggregation densely fills zero days.
  * Estimated cost = enrolled * cost_per_run_cents.
  * Cached counter beat refresh updates both columns + zeroes
    workflows with no recent activity.

Mirrors the ``test_ab_testing.py`` style: workflows + runs +
step_runs inserted via raw ORM so the focus stays on the analytics
math rather than the canvas plumbing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import analytics as wf_analytics
from src.app.core.workflows import data_access as wf_da
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepRunStatus,
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
            "name": "AnalyticsDemo",
            "slug": f"adem-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _make_workflow(
    test_db,
    *,
    org_id: uuid.UUID,
    cost_per_run_cents: int = 10,
    graph: dict | None = None,
    name: str | None = None,
) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=name or f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph=graph
        or {
            "nodes": [
                {"id": "trig", "type": "trigger.lead_created", "config": {}},
                {
                    "id": "send1",
                    "type": "send.email",
                    "config": {"label": "Welcome email"},
                },
                {"id": "goal1", "type": "goal", "config": {"label": "Won"}},
            ],
            "edges": [
                {"id": "e1", "source": "trig", "target": "send1"},
                {"id": "e2", "source": "send1", "target": "goal1"},
            ],
        },
        goal_node_id="goal1",
        enabled_event_types=["lead.created"],
        cost_per_run_cents=cost_per_run_cents,
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _make_run(
    test_db,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    status: WorkflowRunStatus,
    outcome: WorkflowRunOutcome | None,
    started_at: datetime,
    completed_at: datetime | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        org_id=org_id,
        workflow_id=workflow_id,
        version=1,
        contact_id=None,
        status=status,
        outcome=outcome,
        current_node_id=None,
        state={},
        started_at=started_at,
        completed_at=completed_at,
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)
    return run


async def _make_step(
    test_db,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    node_id: str,
    step_index: int,
    status: WorkflowStepRunStatus,
    skip_reason: str | None = None,
) -> WorkflowStepRun:
    step = WorkflowStepRun(
        org_id=org_id,
        run_id=run_id,
        node_id=node_id,
        step_index=step_index,
        status=status,
        skip_reason=skip_reason,
        payload={},
    )
    test_db.add(step)
    await test_db.commit()
    await test_db.refresh(step)
    return step


# ---------------------------------------------------------------------------
# Headline counters
# ---------------------------------------------------------------------------


async def test_aggregate_runs_in_window_counts_correctly(test_db, org_id):
    """Headline counters reflect seeded run statuses + outcomes."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        now = datetime.now(UTC)
        # 5 completed-with-goal, 2 completed-without-goal, 1 errored,
        # 1 running.
        for _ in range(5):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf.id,
                status=WorkflowRunStatus.completed,
                outcome=WorkflowRunOutcome.goal_reached,
                started_at=now - timedelta(hours=1),
                completed_at=now,
            )
        for _ in range(2):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf.id,
                status=WorkflowRunStatus.completed,
                outcome=WorkflowRunOutcome.completed,
                started_at=now - timedelta(hours=1),
                completed_at=now,
            )
        await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            status=WorkflowRunStatus.errored,
            outcome=WorkflowRunOutcome.errored,
            started_at=now - timedelta(hours=1),
        )
        await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            status=WorkflowRunStatus.running,
            outcome=None,
            started_at=now - timedelta(hours=1),
        )

        result = await wf_da.aggregate_runs_in_window(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            since=now - timedelta(days=1),
            until=now + timedelta(hours=1),
        )
    finally:
        reset_context(token)
    assert result["enrolled"] == 9
    assert result["completed"] == 7
    assert result["goal_reached"] == 5
    assert result["errored"] == 1
    assert result["running"] == 1
    # All completed runs took ~1h → avg ~3600s.
    assert result["avg_completion_seconds"] is not None
    assert 3500 < result["avg_completion_seconds"] < 3700


async def test_compute_metrics_emits_conversion_rate_and_cost(test_db, org_id):
    """Top-level metrics dict carries conversion_rate +
    estimated_cost_cents."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id, cost_per_run_cents=25)
        now = datetime.now(UTC)
        for _ in range(2):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf.id,
                status=WorkflowRunStatus.completed,
                outcome=WorkflowRunOutcome.goal_reached,
                started_at=now,
                completed_at=now,
            )
        for _ in range(8):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf.id,
                status=WorkflowRunStatus.completed,
                outcome=WorkflowRunOutcome.completed,
                started_at=now,
                completed_at=now,
            )
        metrics = await wf_analytics.compute_workflow_metrics(
            test_db,
            org_id=org_id,
            workflow=wf,
            since=now - timedelta(days=1),
            until=now + timedelta(hours=1),
        )
    finally:
        reset_context(token)
    assert metrics["totals"]["conversion_rate"] == pytest.approx(0.2)
    # 10 enrolments * 25c each = 250c.
    assert metrics["totals"]["estimated_cost_cents"] == 250


# ---------------------------------------------------------------------------
# Funnel + skip reasons
# ---------------------------------------------------------------------------


async def test_funnel_returns_ordered_per_node_counts(test_db, org_id):
    """Funnel is ordered by graph BFS from the trigger so the
    dashboard renders the flow in natural order."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        now = datetime.now(UTC)
        run = await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.goal_reached,
            started_at=now,
            completed_at=now,
        )
        await _make_step(
            test_db,
            org_id=org_id,
            run_id=run.id,
            node_id="trig",
            step_index=0,
            status=WorkflowStepRunStatus.completed,
        )
        await _make_step(
            test_db,
            org_id=org_id,
            run_id=run.id,
            node_id="send1",
            step_index=1,
            status=WorkflowStepRunStatus.completed,
        )
        metrics = await wf_analytics.compute_workflow_metrics(
            test_db,
            org_id=org_id,
            workflow=wf,
            since=now - timedelta(days=1),
            until=now + timedelta(hours=1),
        )
    finally:
        reset_context(token)
    funnel = metrics["funnel"]
    assert [r["node_id"] for r in funnel[:2]] == ["trig", "send1"]
    assert funnel[1]["label"] == "Welcome email"


async def test_skip_reason_breakdown_per_step(test_db, org_id):
    """``skip_reasons`` maps node_id → {reason: count}."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        now = datetime.now(UTC)
        run = await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.completed,
            started_at=now,
            completed_at=now,
        )
        for _ in range(3):
            await _make_step(
                test_db,
                org_id=org_id,
                run_id=run.id,
                node_id="send1",
                step_index=len((await _list_run_steps(test_db, run.id))),
                status=WorkflowStepRunStatus.skipped,
                skip_reason="opt_out",
            )
        await _make_step(
            test_db,
            org_id=org_id,
            run_id=run.id,
            node_id="send1",
            step_index=len((await _list_run_steps(test_db, run.id))),
            status=WorkflowStepRunStatus.skipped,
            skip_reason="frequency_cap",
        )
        metrics = await wf_analytics.compute_workflow_metrics(
            test_db,
            org_id=org_id,
            workflow=wf,
            since=now - timedelta(days=1),
            until=now + timedelta(hours=1),
        )
    finally:
        reset_context(token)
    breakdown = metrics["skip_reasons"]["send1"]
    assert breakdown == {"opt_out": 3, "frequency_cap": 1}


async def _list_run_steps(test_db, run_id):
    from sqlalchemy import select

    return list(
        (
            await test_db.execute(
                select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id)
            )
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Daily rate
# ---------------------------------------------------------------------------


async def test_daily_rate_densely_fills_zero_days(test_db, org_id):
    """``compute_daily_rate`` returns a row per day in the window even
    for days with no runs."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        # One run today, two yesterday, none day-before.
        await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf.id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.goal_reached,
            started_at=now,
            completed_at=now,
        )
        for _ in range(2):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf.id,
                status=WorkflowRunStatus.completed,
                outcome=WorkflowRunOutcome.completed,
                started_at=now - timedelta(days=1),
                completed_at=now - timedelta(days=1),
            )
        series = await wf_analytics.compute_daily_rate(
            test_db, org_id=org_id, workflow=wf, days=3, now=now
        )
    finally:
        reset_context(token)
    assert len(series) == 3
    # Series order: oldest day → today.
    assert series[0]["enrolled"] == 0
    assert series[1]["enrolled"] == 2
    assert series[2]["enrolled"] == 1
    assert series[2]["goal_reached"] == 1


# ---------------------------------------------------------------------------
# Cached counters refresh
# ---------------------------------------------------------------------------


async def test_refresh_cached_counters_updates_and_zeros(test_db, org_id):
    """The 5-min beat updates both columns + zeroes workflows whose
    counts have aged out."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf_active = await _make_workflow(test_db, org_id=org_id, name="A")
        wf_dormant = await _make_workflow(test_db, org_id=org_id, name="B")
        # Pre-set the dormant workflow's cached counters so the
        # refresh has something to zero.
        wf_dormant.cached_running_count = 999
        wf_dormant.cached_completed_today_count = 999
        await test_db.commit()

        now = datetime.now(UTC)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # wf_active: 2 running + 1 completed today + 1 completed yesterday.
        for _ in range(2):
            await _make_run(
                test_db,
                org_id=org_id,
                workflow_id=wf_active.id,
                status=WorkflowRunStatus.running,
                outcome=None,
                started_at=now,
            )
        await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf_active.id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.goal_reached,
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        )
        await _make_run(
            test_db,
            org_id=org_id,
            workflow_id=wf_active.id,
            status=WorkflowRunStatus.completed,
            outcome=WorkflowRunOutcome.completed,
            started_at=today_midnight - timedelta(hours=4),
            completed_at=today_midnight - timedelta(hours=2),
        )

        await wf_da.refresh_cached_counters(
            test_db, today_midnight_utc=today_midnight
        )
        await test_db.commit()
        await test_db.refresh(wf_active)
        await test_db.refresh(wf_dormant)
    finally:
        reset_context(token)
    assert wf_active.cached_running_count == 2
    assert wf_active.cached_completed_today_count == 1
    assert wf_dormant.cached_running_count == 0
    assert wf_dormant.cached_completed_today_count == 0
