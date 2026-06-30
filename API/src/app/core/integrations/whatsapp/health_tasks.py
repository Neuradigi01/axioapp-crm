"""Hourly phone-health refresh Celery task
(whatsapp-platform-upgrade Step 12).

One beat-driven task — :func:`refresh_phone_health_all_orgs` — that
iterates every org with a connected WhatsApp integration and calls
the health-service refresh path. Per-org failures are logged and the
loop continues so one broken integration doesn't stall everyone
else's refresh.

The task is rate-friendly: at most one Graph API call per org per
hour. For deploys with 1,000 orgs that's ~16 calls/min on the worker
side — well inside Meta's per-token rate limits.

Mirrors the celery-absent shim shape of
``src.app.core.campaigns.tasks`` so dev shells without Celery
installed don't break import."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text as sql_text

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

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        return _wrap


logger = logging.getLogger(__name__)


@_shared_task(
    name="src.app.core.integrations.whatsapp.health_tasks.refresh_phone_health_all_orgs",
)
def refresh_phone_health_all_orgs() -> dict[str, Any]:
    """Beat-driven hourly sweep. Iterates connected WhatsApp orgs,
    refreshes phone-health from Meta, writes timeline events for any
    deltas. Per-org failures don't fail the whole task."""
    return asyncio.run(_refresh_phone_health_all_orgs_async())


async def _refresh_phone_health_all_orgs_async() -> dict[str, Any]:
    from src.app.core.integrations.whatsapp.health_service import (
        refresh_from_meta,
    )
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    refreshed = 0
    failed = 0

    async with async_session() as session:
        # Bypass-tenant scan — beat has no tenant context. Pull every
        # active WhatsApp integration's org_id, then re-enter per-org
        # with the right context for RLS-scoped DB writes.
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                    SELECT i.org_id
                    FROM tbl_integrations i
                    WHERE i.provider = 'whatsapp'
                      AND i.status = 'connected'
                      AND i.access_token_enc IS NOT NULL
                    """
                    )
                )
            )
            .mappings()
            .all()
        )

        for row in rows:
            org_id = row["org_id"]
            token = set_context(RequestContext(org_id=org_id, user_id=None))
            try:
                await refresh_from_meta(session)
                refreshed += 1
            except Exception:
                logger.exception("phone_health refresh failed for org %s", org_id)
                failed += 1
                # Roll back so the next iteration's session is clean.
                await session.rollback()
            finally:
                reset_context(token)

    logger.info("phone_health refresh: %d refreshed, %d failed", refreshed, failed)
    return {"refreshed": refreshed, "failed": failed}


__all__ = ["refresh_phone_health_all_orgs"]
