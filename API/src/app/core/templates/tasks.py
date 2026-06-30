"""Hourly external-status sweep Celery task
(``tasks/template-library`` Step 14).

One beat-driven task — :func:`sync_external_status_all` — iterates
every org with at least one ``pending`` or ``paused`` central
template and runs :func:`core.templates.sync.sync_all_pending` under
the org's RLS context. Per-org failures are logged + the loop
continues so one broken integration doesn't stall the others.

Rate-friendly: at most one Meta Graph call per pending-template per
org per hour. Even at 1,000 orgs × 5 pending templates = 5,000
calls/hour worker-side — well inside Meta's per-token rate limit.

Mirrors the celery-absent shim shape of
:mod:`core.integrations.whatsapp.health_tasks` so dev shells without
Celery installed don't break import."""

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
    name="src.app.core.templates.tasks.sync_external_status_all",
)
def sync_external_status_all() -> dict[str, Any]:
    """Beat-driven hourly sweep. Resolves the Meta App credentials
    from the SOPS-managed config once, then iterates every org with
    a connected WhatsApp integration AND at least one pending /
    paused central template. Per-org rollbacks on failure."""
    return asyncio.run(_sync_external_status_all_async())


async def _sync_external_status_all_async() -> dict[str, Any]:
    from src.app.core.templates.sync import sync_all_pending
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    try:
        from config import META_APP_ID, WHATSAPP_APP_SECRET
    except ImportError:  # pragma: no cover — dev config missing
        logger.error("templates.sync sweep skipped: Meta credentials missing")
        return {"checked": 0, "updated": 0, "failed": 0, "skipped": True}

    if not META_APP_ID or not WHATSAPP_APP_SECRET:
        logger.error("templates.sync sweep skipped: Meta credentials empty")
        return {"checked": 0, "updated": 0, "failed": 0, "skipped": True}

    total_checked = 0
    total_updated = 0
    total_failed = 0
    orgs_visited = 0

    async with async_session() as session:
        # Bypass-tenant scan — beat has no tenant context. Pull every
        # org that has both a connected WA integration AND at least
        # one pending/paused central template. The double-join keeps
        # the loop tight: orgs that connect WA but never submit a
        # template won't show up, neither will orgs whose templates
        # are all approved/archived.
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                    SELECT DISTINCT i.org_id
                    FROM tbl_integrations i
                    JOIN tbl_message_templates t
                      ON t.org_id = i.org_id
                     AND t.external_status IN ('pending', 'paused')
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
            orgs_visited += 1
            token = set_context(RequestContext(org_id=org_id, user_id=None))
            try:
                result = await sync_all_pending(
                    session,
                    org_id=org_id,
                    app_id=META_APP_ID,
                    app_secret=WHATSAPP_APP_SECRET,
                )
                total_checked += result["checked"]
                total_updated += result["updated"]
                total_failed += result["failed"]
            except Exception:
                logger.exception("templates.sync sweep failed for org %s", org_id)
                total_failed += 1
                await session.rollback()
            finally:
                reset_context(token)

    logger.info(
        "templates.sync sweep: orgs=%d checked=%d updated=%d failed=%d",
        orgs_visited,
        total_checked,
        total_updated,
        total_failed,
    )
    return {
        "orgs": orgs_visited,
        "checked": total_checked,
        "updated": total_updated,
        "failed": total_failed,
    }


__all__ = ["sync_external_status_all"]
