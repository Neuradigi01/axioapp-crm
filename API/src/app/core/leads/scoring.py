"""Lead scoring engine.

A rule is an active row in ``lead_scoring_rules``. The score of a lead
is::

    clamp(sum(rule.points for rule in active_rules if rule.matches(lead)), 0, 100)

The engine runs in three places:

  - ``recompute_lead`` — called from ``leads.service.create_lead`` and
    ``leads.service.update_lead`` after the row has been flushed. No
    extra commit; the caller's transaction carries the new
    ``lead_score`` value.
  - ``recompute_org_scores`` — bulk recomputation, used by the Celery
    sweep and by scoring-rule mutations.
  - ``recompute_all_lead_scores`` — the Celery beat task, registered in
    ``src.celery.celery_config.beat_schedule`` with an hourly cadence.

The rule-relevant-fields cache (``_RULE_FIELD_CACHE``) lets
``update_lead`` skip a recompute when none of the changed columns
appear in any active rule. Cache is per-org with a short TTL; on miss
or rule mutation we recompute.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.leads import filter_dsl
from src.app.core.leads.models import Lead, LeadScoringRule

logger = logging.getLogger(__name__)


_SCORE_MIN = 0
_SCORE_MAX = 100


# --- public surface ---------------------------------------------------------


def compute_score(lead: Lead, rules: list[LeadScoringRule]) -> int:
    """Sum the points of every active rule whose condition matches the
    lead. Clamp the total to ``[0, 100]``.

    Inactive rules are filtered out by the caller (the engine never
    sees them) — passing only active rules keeps the inner loop cheap.
    """
    total = 0
    for rule in rules:
        try:
            parsed = filter_dsl.parse(rule.condition)
            if filter_dsl.matches(parsed, lead=lead):
                total += rule.points
        except filter_dsl.FilterDslError:
            # Rules with conditions that can't be evaluated in-memory
            # (e.g. someone edited the JSONB directly to reference a
            # contact field) are skipped with a warning rather than
            # raising — we don't want a single bad rule to break
            # scoring for the org.
            logger.warning(
                "scoring rule %s has an un-evaluable condition; skipped",
                rule.id,
            )
            continue
    return max(_SCORE_MIN, min(_SCORE_MAX, total))


async def fetch_active_rules(session: AsyncSession, *, org_id: uuid.UUID) -> list[LeadScoringRule]:
    """All active rules for the tenant. RLS keeps org isolation; the
    explicit ``org_id`` predicate is belt-and-suspenders."""
    result = await session.execute(
        select(LeadScoringRule)
        .where(
            LeadScoringRule.org_id == org_id,
            LeadScoringRule.active.is_(True),
        )
        .order_by(LeadScoringRule.created_at.asc())
    )
    return list(result.scalars())


async def recompute_lead(
    session: AsyncSession,
    *,
    lead: Lead,
    rules: list[LeadScoringRule] | None = None,
) -> int:
    """Recompute and persist ``lead.lead_score``. Returns the new score.

    Does not commit — the caller decides when the transaction lands.
    Pass ``rules`` to skip the per-call SELECT when scoring many
    leads in a row (``recompute_org_scores`` does this).
    """
    if rules is None:
        rules = await fetch_active_rules(session, org_id=lead.org_id)
    new_score = compute_score(lead, rules)
    if lead.lead_score != new_score:
        lead.lead_score = new_score
        await session.flush()
    return new_score


async def recompute_org_scores(session: AsyncSession, *, org_id: uuid.UUID) -> int:
    """Bulk-recompute every lead in the org. Returns rows touched.

    Streams leads in keyset batches of 500 ordered by id. Keyset
    walking avoids the deep-offset O(N²) scan the previous
    ``.offset(offset)`` approach did on 10k+-lead orgs — Postgres
    used to re-scan the first ``offset`` rows before returning the
    batch. Now every batch is a bounded index-range read.

    Commits once at the end — the caller is responsible for any
    larger transaction it wants to wrap this in.
    """
    rules = await fetch_active_rules(session, org_id=org_id)
    touched = 0
    batch_size = 500
    last_id: uuid.UUID | None = None
    while True:
        stmt = (
            select(Lead)
            .where(Lead.org_id == org_id)
            .order_by(Lead.id)
            .limit(batch_size)
        )
        if last_id is not None:
            stmt = stmt.where(Lead.id > last_id)
        result = await session.execute(stmt)
        batch = list(result.scalars())
        if not batch:
            break
        for lead in batch:
            new_score = compute_score(lead, rules)
            if lead.lead_score != new_score:
                lead.lead_score = new_score
                touched += 1
            last_id = lead.id
        await session.flush()
        if len(batch) < batch_size:
            break
    await session.commit()
    # The rule-relevant-fields cache is keyed by org; invalidate
    # because some rules may have changed before the caller invoked us.
    _RULE_FIELD_CACHE.pop(org_id, None)
    return touched


# --- rule-relevant-fields cache --------------------------------------------


_RULE_FIELD_CACHE_TTL_SEC = 60.0
# (timestamp, set_of_fields) per org. Module-global is acceptable: the
# scoring sweep is a single-process Celery worker, and the API workers
# tolerate the 60s staleness gracefully (worst case: a recompute fires
# when it didn't need to).
_RULE_FIELD_CACHE: dict[uuid.UUID, tuple[float, set[str]]] = {}


async def rule_relevant_fields(session: AsyncSession, *, org_id: uuid.UUID) -> set[str]:
    """The union of fields referenced by any active rule's condition,
    used by ``update_lead`` to short-circuit unnecessary recomputes.

    Returns the empty set when no rules exist; ``update_lead`` treats
    that as "never recompute on update" and the no-op path is taken.
    """
    now = time.monotonic()
    cached = _RULE_FIELD_CACHE.get(org_id)
    if cached is not None and (now - cached[0]) < _RULE_FIELD_CACHE_TTL_SEC:
        return cached[1]
    rules = await fetch_active_rules(session, org_id=org_id)
    fields: set[str] = set()
    for rule in rules:
        try:
            fields |= filter_dsl.fields_referenced(filter_dsl.parse(rule.condition))
        except filter_dsl.FilterDslError:
            # Same loud-skip stance as compute_score.
            logger.warning(
                "scoring rule %s has an un-parsable condition; skipped",
                rule.id,
            )
            continue
    _RULE_FIELD_CACHE[org_id] = (now, fields)
    return fields


def invalidate_rule_field_cache(org_id: uuid.UUID) -> None:
    """Drop the cached field set for one org. Called from the rule
    CRUD service on any mutation."""
    _RULE_FIELD_CACHE.pop(org_id, None)


# --- Celery task ------------------------------------------------------------

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery absent in dev shells
    HAS_CELERY = False

    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        return _wrap


@_shared_task(
    name="src.app.core.leads.scoring.recompute_all_lead_scores",
)
def recompute_all_lead_scores() -> None:
    """Beat task — recompute scores for every active org hourly.

    Iterates orgs and runs ``recompute_org_scores`` per org. Each org's
    recompute is independent; a failure for one org logs and continues.

    Wraps the async core in ``asyncio.run`` because Celery's worker
    threads don't carry an event loop. The async session uses the same
    DB engine as the API workers.
    """
    import asyncio

    asyncio.run(_recompute_all_orgs())


async def _recompute_all_orgs() -> None:
    from sqlalchemy import text

    from src.app.core.tenants.models import Organization
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    # We're outside the API's TenantContextMiddleware here, so RLS would
    # deny everything. Open one session per org and stamp the context.
    org_ids: list[uuid.UUID] = []
    async with async_session() as session:
        result = await session.execute(select(Organization.id))
        org_ids = [row[0] for row in result.all()]

    for org_id in org_ids:
        token = set_context(RequestContext(org_id=org_id))
        try:
            async with async_session() as session:
                # Belt + suspenders: also stamp the PG session variable
                # so RLS policies authorise the scan. The TenantContext
                # middleware does this for API requests; we're in a
                # background task, so do it explicitly.
                await session.execute(
                    text("SELECT set_config('app.org_id', :v, true)"),
                    {"v": str(org_id)},
                )
                try:
                    await recompute_org_scores(session, org_id=org_id)
                except Exception:
                    logger.exception("lead-score recompute failed for org=%s", org_id)
        finally:
            reset_context(token)


__all__ = [
    "HAS_CELERY",
    "compute_score",
    "fetch_active_rules",
    "invalidate_rule_field_cache",
    "recompute_all_lead_scores",
    "recompute_lead",
    "recompute_org_scores",
    "rule_relevant_fields",
]
