"""Nightly sweeper for orphan channel endpoints.

Runs at 03:15 UTC via ``celery_config.beat_schedule``. Sweeps two
classes of drift the model tolerates but wants cleaned up:

  * **Orphan endpoints** — ``tbl_channel_endpoints`` rows with no
    matching ``tbl_email_endpoint_details`` row, older than 24 h.
    Backfill (Step 1) makes this impossible today, but code drift or
    a partial insert (details row rolled back, endpoint kept) is the
    kind of thing a sweeper defends against.

  * **OAuth endpoints backed by revoked accounts** —
    ``endpoint_type='oauth_mailbox'`` where the FK'd
    ``tbl_email_accounts`` row has been in ``disconnected`` state
    for the whole 7-day grace window. Users who revoke a Gmail /
    Microsoft grant sometimes never reconnect; the stale endpoint
    row keeps showing up in the admin overview until we clean it.

Both classes are **soft-deleted** (``is_active=false``,
``deactivated_at=now()``, ``deactivation_reason=<code>``) so an
operator can inspect the record afterwards. Hard-delete lives in a
future retention track.

Best-effort: a per-row exception logs + skips + counts as ``failed``.
Return value is a summary dict (matches the ``sweep_orphan_pending_orgs``
shape the tenants module ships).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.app.core.channel_endpoints import data_access as endpoints_da
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)


# Orphan endpoint = no ``tbl_email_endpoint_details`` row after 24 h.
_ORPHAN_MIN_AGE_HOURS = 24

# OAuth account must have been ``disconnected`` for this whole grace
# window before we soft-delete the backing endpoint. 7 days is long
# enough that "I revoked by mistake" reconnects still land on the
# same endpoint row; anything longer is real abandonment.
_OAUTH_DISCONNECTED_GRACE_DAYS = 7


@celery.task(
    name="src.app.core.channel_endpoints.tasks.sweep_orphan_endpoints",
    bind=True,
)
def sweep_orphan_endpoints(self) -> dict[str, Any]:  # noqa: ARG001
    """Beat-triggered nightly. See module docstring."""
    return asyncio.run(_sweep_orphan_endpoints_async())


async def _sweep_orphan_endpoints_async() -> dict[str, Any]:
    now = datetime.now(UTC)
    orphan_cutoff = now - timedelta(hours=_ORPHAN_MIN_AGE_HOURS)
    disconnected_cutoff = now - timedelta(days=_OAUTH_DISCONNECTED_GRACE_DAYS)

    orphan_swept = 0
    oauth_swept = 0
    failed = 0
    swept_ids: list[str] = []

    async with async_session() as session:
        # --- Orphan endpoints (no details row after grace window) ---
        try:
            orphans = await endpoints_da.list_orphan_endpoints(
                session, cutoff_dt=orphan_cutoff
            )
            for e in orphans:
                await endpoints_da.deactivate(
                    session, endpoint=e, reason="orphan_sweeper"
                )
                orphan_swept += 1
                swept_ids.append(str(e.id))
        except Exception:  # noqa: BLE001 — surface + continue
            logger.exception("sweep_orphan_endpoints: orphan pass failed")
            failed += 1

        # --- OAuth endpoints backed by long-disconnected accounts ---
        try:
            oauth_orphans = await (
                endpoints_da.list_oauth_endpoints_backed_by_disconnected_accounts(
                    session, disconnected_since=disconnected_cutoff
                )
            )
            for e in oauth_orphans:
                await endpoints_da.deactivate(
                    session,
                    endpoint=e,
                    reason="oauth_account_disconnected",
                )
                oauth_swept += 1
                swept_ids.append(str(e.id))
        except Exception:  # noqa: BLE001
            logger.exception(
                "sweep_orphan_endpoints: oauth-disconnected pass failed"
            )
            failed += 1

        if orphan_swept or oauth_swept:
            await session.commit()

    if orphan_swept or oauth_swept:
        logger.info(
            "sweep_orphan_endpoints soft-deleted %d orphan + %d oauth-disconnected endpoint(s) ids=%s",
            orphan_swept,
            oauth_swept,
            swept_ids,
        )

    return {
        "orphan_swept": orphan_swept,
        "oauth_swept": oauth_swept,
        "failed": failed,
        "swept_ids": swept_ids,
        "at": now.isoformat(),
    }


__all__ = ["sweep_orphan_endpoints"]
