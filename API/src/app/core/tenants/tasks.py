"""Celery tasks for the tenants module.

Currently one task:

  * :func:`sweep_orphan_pending_orgs` — nightly cross-tenant sweep that
    deletes organizations still stuck in ``template_id="pending"`` more
    than 48 hours after signup. A pending org is what
    ``register_user_only`` creates as the first stage of the two-stage
    signup; if the user abandons before the onboarding picker completes,
    that org sits forever with a trial subscription ticking down, its
    single membership never activated. Left alone they accumulate as
    dead rows in ``tbl_organizations`` and inflate the trial-lifecycle
    beat's working set.

Deleted rows:

  * ``tbl_auth_sessions`` for the org — the abandoning user's JWTs
    stop being useful (they'll get 401 on next request; the frontend
    guard bounces to login).
  * ``tbl_subscriptions`` for the org — no billing side-effect because
    the row was still ``trialing``, never activated by Stripe.
  * ``tbl_organization_members`` for the org — captures the single
    user_member_id as we go.
  * ``tbl_organizations`` itself.
  * If a captured user_member_id has no *other* memberships, we also
    drop their ``tbl_user_login`` + ``tbl_user_info`` so the email can
    be reused for a fresh signup.

Best-effort per org: any exception during a single org's cleanup is
logged and the sweep moves on to the next candidate. The task is
idempotent — re-runs simply find fewer candidates each time.

Beat schedule: ``crontab(hour=3, minute=45)`` — 03:45 UTC, offset from
the other daily and hourly sweeps so we don't contend on the DB pool.

Follows the celery-absent shim shape from
:mod:`src.app.core.tasks.tasks` so dev shells without Celery installed
don't break import.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any


try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover — celery absent in dev shells
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

                def apply_async(self, args=None, kwargs=None, **_):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        return _wrap


logger = logging.getLogger(__name__)


# Pending orgs younger than this are treated as "still in progress" —
# a user just typing through the onboarding picker. Two days is well
# beyond any realistic wizard duration; anything older is abandoned.
_ORPHAN_THRESHOLD_HOURS = 48


@_shared_task(
    name="src.app.core.tenants.tasks.sweep_orphan_pending_orgs",
)
def sweep_orphan_pending_orgs() -> dict[str, Any]:
    """Beat-triggered daily. See module docstring."""
    return asyncio.run(_sweep_orphan_pending_orgs_async())


async def _sweep_orphan_pending_orgs_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.shared.db import async_session

    deleted_orgs = 0
    deleted_users = 0
    failed = 0

    async with async_session() as session:
        # Raw SQL to bypass the ORM tenant filter — this task is
        # explicitly cross-tenant. Same pattern as
        # ``groom_stale_open_tasks`` and
        # ``google_calendar.tasks.reconcile_pending``.
        candidates = (
            await session.execute(
                text(
                    """
                    SELECT id
                      FROM tbl_organizations
                     WHERE template_id = 'pending'
                       AND created_at < now() - make_interval(hours => :hours)
                    """
                ),
                {"hours": _ORPHAN_THRESHOLD_HOURS},
            )
        ).all()

    for row in candidates:
        try:
            users_dropped = await _delete_orphan_org(row.id)
            deleted_orgs += 1
            deleted_users += users_dropped
            await _write_audit(org_id=row.id)
        except Exception:  # noqa: BLE001 — per-org best-effort
            failed += 1
            logger.exception(
                "sweep_orphan_pending_orgs org_delete_failed org=%s",
                row.id,
            )

    return {
        "deleted_orgs": deleted_orgs,
        "deleted_users": deleted_users,
        "failed": failed,
        "at": datetime.now(UTC).isoformat(),
    }


async def _delete_orphan_org(org_id: uuid.UUID) -> int:
    """Delete one pending org + its dependents in a single transaction.

    Returns the number of ``tbl_user_login`` rows dropped alongside the
    org (users whose only membership was this pending org).
    """
    from sqlalchemy import text

    from src.app.shared.db import async_session

    async with async_session() as session:
        # Capture the members' user_member_ids before we drop the
        # membership rows, so we can check downstream whether they
        # have any other active memberships worth keeping their
        # tbl_user_login for.
        member_rows = (
            await session.execute(
                text(
                    """
                    SELECT user_member_id
                      FROM tbl_organization_members
                     WHERE organization_id = :org_id
                    """
                ),
                {"org_id": org_id},
            )
        ).all()
        candidate_user_member_ids = [m.user_member_id for m in member_rows]

        # Drop dependents in FK-safe order. Each DELETE is idempotent
        # (WHERE org_id / organization_id predicate); a run that finds
        # zero rows for any of them is fine.
        await session.execute(
            text("DELETE FROM tbl_auth_sessions WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
        await session.execute(
            text("DELETE FROM tbl_subscriptions WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
        await session.execute(
            text("DELETE FROM tbl_organization_members WHERE organization_id = :org_id"),
            {"org_id": org_id},
        )
        await session.execute(
            text("DELETE FROM tbl_organizations WHERE id = :org_id"),
            {"org_id": org_id},
        )

        # Now that memberships are gone, drop the user rows that no
        # longer belong to *any* org. Freeing the email lets the same
        # person retry signup without a 409 from ``email_exists``.
        users_dropped = 0
        for user_member_id in candidate_user_member_ids:
            remaining = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS n
                          FROM tbl_organization_members
                         WHERE user_member_id = :uid
                        """
                    ),
                    {"uid": user_member_id},
                )
            ).scalar_one()
            if remaining == 0:
                await session.execute(
                    text("DELETE FROM tbl_user_info WHERE member_id = :uid"),
                    {"uid": user_member_id},
                )
                await session.execute(
                    text("DELETE FROM tbl_user_login WHERE id = :uid"),
                    {"uid": user_member_id},
                )
                users_dropped += 1

        await session.commit()

    return users_dropped


async def _write_audit(*, org_id: uuid.UUID) -> None:
    """Emit ``org.orphan_pending_deleted`` after successful cleanup.

    Writing the audit *outside* the org's own tenant context because
    the org is already gone — pin the entry to a system context so it
    is queryable via the cross-tenant audit surface.
    """
    from src.app.shared.audit import log_entity_change
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )

    # Point the writer at a system context (no org_id). The audit sink
    # accepts entries without a tenant scope for cross-tenant janitor
    # actions like this one.
    token = set_context(RequestContext(org_id=None, user_id=None))
    try:
        await log_entity_change(
            action="org.orphan_pending_deleted",
            entity_type="organization",
            entity_id=org_id,
            after={"reason": "template_id_pending_over_48h"},
        )
    finally:
        reset_context(token)


__all__ = ["sweep_orphan_pending_orgs"]
