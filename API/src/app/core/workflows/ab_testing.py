"""A/B testing utilities for the workflows engine — Step 18.

Three public entry points:

  * :func:`enroll_with_ab_split` — deterministic 50/50 split. Given
    a workflow whose ``ab_paired_workflow_id`` is set, returns the
    workflow (self or the paired sibling) that a contact's enrolment
    should land on. The choice is hashed off
    ``(contact_id, workflow_pair_key)`` so the same contact always
    routes to the same variant on re-enrolment — making re-runs of a
    cancelled / errored A/B test stable across worker restarts.

  * :func:`pick_winner` — runs the conversion-rate calc against
    ``tbl_workflow_runs`` for both siblings. Returns a dict with
    ``winner: 'a' | 'b' | 'inconclusive'`` plus the per-side rates,
    sample sizes, and a two-proportion z-test p-value. The picker
    enforces a minimum-sample-size floor (per-side ``min_runs``)
    before declaring confidence.

  * :func:`auto_promote` — winner.status=active, loser.status=archived,
    both rows stamped with ``ab_test_winner_workflow_id`` and
    ``ab_test_decided_at`` so the canvas banner can render the
    decision. The loser keeps existing in-flight runs (no mid-stream
    cancellation — the spec rule).

The beat task in :mod:`core.workflows.tasks` calls
:func:`evaluate_pair_for_decision` once an hour to drive the
holdback-expiry sweep.
"""
from __future__ import annotations

import hashlib
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowStatus,
)


logger = logging.getLogger(__name__)


# Beat-task ceiling on how long the holdback can stretch under the
# "extend by 50% on inconclusive" rule — past this we stop bumping the
# clock and just leave the test as "inconclusive — pick manually".
_MAX_TOTAL_HOLDBACK = timedelta(days=30)


@dataclass(slots=True)
class PickWinnerResult:
    """Return value of :func:`pick_winner`."""

    winner: str  # 'a' | 'b' | 'inconclusive'
    a_total: int
    a_goal: int
    a_rate: float
    b_total: int
    b_goal: int
    b_rate: float
    p_value: float | None
    reason: str  # one-line human-readable summary

    def as_dict(self) -> dict:
        return {
            "winner": self.winner,
            "a_total_runs": self.a_total,
            "a_goal_runs": self.a_goal,
            "a_rate": self.a_rate,
            "b_total_runs": self.b_total,
            "b_goal_runs": self.b_goal,
            "b_rate": self.b_rate,
            "p_value": self.p_value,
            "reason": self.reason,
        }


# --- enroll_with_ab_split -------------------------------------------------


def _pair_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """Stable string key for a workflow pair regardless of which side
    the caller passed in. Sorting the two UUIDs guarantees both
    siblings hash against the same pair key so the split routes
    consistently no matter which side the engine starts from."""
    lo, hi = sorted((str(a), str(b)))
    return f"{lo}:{hi}"


def _split_pick_a(contact_id: uuid.UUID | None, pair_key: str) -> bool:
    """True → variant A; False → variant B.

    Hash on SHA-256(``contact_id + pair_key``) first byte. Contact-less
    enrolments (org-wide events) hash off the pair key alone — the
    split is still deterministic per pair but every contact-less event
    lands on the same side. Acceptable for v1 because operators very
    rarely build contact-less A/B tests.
    """
    seed = f"{contact_id or 'anonymous'}|{pair_key}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return digest[0] % 2 == 0


async def enroll_with_ab_split(
    session: AsyncSession,
    *,
    workflow: Workflow,
    contact_id: uuid.UUID | None,
) -> Workflow:
    """Pick the variant the engine should actually enrol the contact in.

    Returns the input workflow unchanged when:
      * the workflow isn't paired (``ab_paired_workflow_id is None``);
      * the test has already been decided (``ab_test_decided_at is
        not None``) — every new enrolment goes to the winner;
      * the paired sibling can't be loaded (FK was nulled out by a
        sibling-deletion cascade).

    Otherwise loads the sibling and returns whichever side the
    deterministic hash picks. The returned workflow is what
    :func:`engine.start_run` enrols the contact into.
    """
    paired_id = workflow.ab_paired_workflow_id
    if paired_id is None:
        return workflow

    # Post-decision: every event routes to the winner regardless of
    # which side the matcher matched on (handles the case where a
    # subscriber matched the loser by event_type — we want them on
    # the winner).
    if workflow.ab_test_winner_workflow_id is not None:
        if workflow.ab_test_winner_workflow_id == workflow.id:
            return workflow
        winner = await session.get(
            Workflow, workflow.ab_test_winner_workflow_id
        )
        return winner or workflow

    sibling = await session.get(Workflow, paired_id)
    if sibling is None:
        return workflow

    pair_key = _pair_key(workflow.id, sibling.id)
    if _split_pick_a(contact_id, pair_key):
        # Variant A is the workflow whose id sorts FIRST in the pair
        # key — guarantees the same physical workflow is "A" no
        # matter which sibling the matcher started from.
        return workflow if str(workflow.id) < str(sibling.id) else sibling
    else:
        return sibling if str(workflow.id) < str(sibling.id) else workflow


# --- pick_winner ---------------------------------------------------------


async def _count_runs(
    session: AsyncSession, *, workflow_id: uuid.UUID
) -> tuple[int, int]:
    """Return ``(total_runs, goal_runs)`` for one workflow id.

    Goal runs = runs whose ``outcome == WorkflowRunOutcome.goal_reached``.
    A run that's still pending or running counts toward the total but
    not the goal — under-counts conversions if a test ends before the
    last cohort finishes; acceptable per the spec (operators pick
    holdback windows long enough for runs to complete).
    """
    total = (
        await session.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
        )
    ).scalar_one()
    goal = (
        await session.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.outcome == WorkflowRunOutcome.goal_reached,
            )
        )
    ).scalar_one()
    return int(total or 0), int(goal or 0)


def _two_proportion_z_p_value(
    *, x1: int, n1: int, x2: int, n2: int
) -> float | None:
    """Two-proportion z-test, returns the two-sided p-value.

    Returns ``None`` when the test is undefined (n1=0 or n2=0 or the
    pooled standard error collapses to 0). The picker treats ``None``
    as "inconclusive" + waits for more data.
    """
    if n1 == 0 or n2 == 0:
        return None
    p1 = x1 / n1
    p2 = x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    denom_sq = p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)
    if denom_sq <= 0:
        return None
    se = math.sqrt(denom_sq)
    z = (p1 - p2) / se
    # Two-sided p-value via the normal CDF approximation.
    return math.erfc(abs(z) / math.sqrt(2))


async def pick_winner(
    session: AsyncSession,
    *,
    a_workflow_id: uuid.UUID,
    b_workflow_id: uuid.UUID,
    min_runs_per_variant: int = 50,
    significance_threshold: float = 0.05,
) -> PickWinnerResult:
    """Compute conversion rates + significance for the paired siblings.

    Returns ``winner='inconclusive'`` when either side has fewer than
    ``min_runs_per_variant`` runs OR the two-proportion z-test
    p-value is >= ``significance_threshold``.
    """
    a_total, a_goal = await _count_runs(session, workflow_id=a_workflow_id)
    b_total, b_goal = await _count_runs(session, workflow_id=b_workflow_id)
    a_rate = a_goal / a_total if a_total else 0.0
    b_rate = b_goal / b_total if b_total else 0.0

    if a_total < min_runs_per_variant or b_total < min_runs_per_variant:
        return PickWinnerResult(
            winner="inconclusive",
            a_total=a_total,
            a_goal=a_goal,
            a_rate=a_rate,
            b_total=b_total,
            b_goal=b_goal,
            b_rate=b_rate,
            p_value=None,
            reason=(
                f"insufficient sample: a={a_total} b={b_total} "
                f"(min {min_runs_per_variant} per variant)"
            ),
        )

    p_value = _two_proportion_z_p_value(
        x1=a_goal, n1=a_total, x2=b_goal, n2=b_total
    )
    if p_value is None or p_value >= significance_threshold:
        return PickWinnerResult(
            winner="inconclusive",
            a_total=a_total,
            a_goal=a_goal,
            a_rate=a_rate,
            b_total=b_total,
            b_goal=b_goal,
            b_rate=b_rate,
            p_value=p_value,
            reason=(
                f"p={p_value:.3f} >= {significance_threshold}"
                if p_value is not None
                else "z-test undefined (zero variance)"
            ),
        )

    winner = "a" if a_rate >= b_rate else "b"
    return PickWinnerResult(
        winner=winner,
        a_total=a_total,
        a_goal=a_goal,
        a_rate=a_rate,
        b_total=b_total,
        b_goal=b_goal,
        b_rate=b_rate,
        p_value=p_value,
        reason=(
            f"winner={winner} a_rate={a_rate:.3f} b_rate={b_rate:.3f} "
            f"p={p_value:.3f}"
        ),
    )


# --- auto_promote --------------------------------------------------------


async def auto_promote(
    session: AsyncSession,
    *,
    winner_workflow_id: uuid.UUID,
    loser_workflow_id: uuid.UUID,
    decided_at: datetime | None = None,
) -> tuple[Workflow, Workflow]:
    """Activate the winner + archive the loser. Stamps both rows with
    ``ab_test_winner_workflow_id`` + ``ab_test_decided_at`` so the
    canvas banner + comparison page render the decision.

    Loser keeps in-flight runs — the engine's ``_execute_current_node``
    check (workflow.status==archived → cancel) only applies on the
    NEXT hop, so runs already past their last node settle normally."""
    decided = decided_at or datetime.now(timezone.utc)
    winner = await session.get(Workflow, winner_workflow_id)
    loser = await session.get(Workflow, loser_workflow_id)
    if winner is None or loser is None:
        raise ValueError(
            f"A/B auto_promote: missing workflow "
            f"winner={winner_workflow_id} loser={loser_workflow_id}"
        )
    winner.status = WorkflowStatus.active
    winner.ab_test_winner_workflow_id = winner_workflow_id
    winner.ab_test_decided_at = decided
    loser.status = WorkflowStatus.archived
    loser.ab_test_winner_workflow_id = winner_workflow_id
    loser.ab_test_decided_at = decided
    return winner, loser


# --- beat-task driver ---------------------------------------------------


async def list_pairs_due_for_decision(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[Workflow]:
    """Return workflows whose ``ab_test_holdback_until <= now`` AND
    whose ``ab_test_decided_at IS NULL`` AND who are the "primary"
    side of the pair (lower-id wins to dedupe — we only need to
    process each pair once, not once per side)."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(Workflow)
        .where(
            Workflow.ab_test_holdback_until.is_not(None),
            Workflow.ab_test_holdback_until <= now,
            Workflow.ab_test_decided_at.is_(None),
            Workflow.ab_paired_workflow_id.is_not(None),
        )
        .order_by(Workflow.ab_test_holdback_until.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    # Dedupe: process each pair from the side whose id sorts FIRST.
    return [
        wf
        for wf in rows
        if str(wf.id) < str(wf.ab_paired_workflow_id)
    ]


async def evaluate_pair_for_decision(
    session: AsyncSession,
    *,
    workflow: Workflow,
    significance_threshold: float = 0.05,
    now: datetime | None = None,
) -> dict:
    """Process one paired workflow.

    Looks at the pair, computes the winner via :func:`pick_winner`,
    and either auto-promotes (decisive) OR extends the holdback by
    50% (inconclusive, up to ``_MAX_TOTAL_HOLDBACK`` total).

    Returns a small dict describing what happened — the beat task
    aggregates these into the log + a notification to the workflow
    owner.
    """
    now = now or datetime.now(timezone.utc)
    sibling_id = workflow.ab_paired_workflow_id
    if sibling_id is None:
        return {"status": "skipped", "reason": "no_sibling"}
    sibling = await session.get(Workflow, sibling_id)
    if sibling is None:
        return {"status": "skipped", "reason": "sibling_missing"}

    # A is the side whose id sorts first — matches `_pair_key`'s
    # contract so the picker's a/b labels stay aligned with the
    # canvas banner's "Variant A" / "Variant B" copy.
    a_workflow, b_workflow = (
        (workflow, sibling)
        if str(workflow.id) < str(sibling.id)
        else (sibling, workflow)
    )

    min_runs = max(
        workflow.ab_test_min_runs_per_variant or 50,
        sibling.ab_test_min_runs_per_variant or 50,
    )
    result = await pick_winner(
        session,
        a_workflow_id=a_workflow.id,
        b_workflow_id=b_workflow.id,
        min_runs_per_variant=min_runs,
        significance_threshold=significance_threshold,
    )

    if result.winner == "inconclusive":
        # Extend the holdback by 50%, capped at MAX_TOTAL.
        started = workflow.ab_test_started_at or now
        current_window = (workflow.ab_test_holdback_until or now) - started
        new_window = current_window + (current_window // 2)
        if new_window > _MAX_TOTAL_HOLDBACK:
            new_window = _MAX_TOTAL_HOLDBACK
        new_until = started + new_window
        workflow.ab_test_holdback_until = new_until
        sibling.ab_test_holdback_until = new_until
        return {
            "status": "extended",
            "new_holdback_until": new_until.isoformat(),
            "result": result.as_dict(),
        }

    winner_id = a_workflow.id if result.winner == "a" else b_workflow.id
    loser_id = b_workflow.id if result.winner == "a" else a_workflow.id
    await auto_promote(
        session,
        winner_workflow_id=winner_id,
        loser_workflow_id=loser_id,
        decided_at=now,
    )
    return {
        "status": "decided",
        "winner_workflow_id": str(winner_id),
        "loser_workflow_id": str(loser_id),
        "result": result.as_dict(),
    }


__all__ = [
    "PickWinnerResult",
    "auto_promote",
    "enroll_with_ab_split",
    "evaluate_pair_for_decision",
    "list_pairs_due_for_decision",
    "pick_winner",
]
