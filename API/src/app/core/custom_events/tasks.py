"""Celery tasks for custom events — hourly date-triggered sweep.

One task today: :func:`sweep_date_triggered_events`. Runs at ``:05``
past every hour so it doesn't contend with :00-anchored jobs
(lead-score recompute, subscription rollover). For each org that has
one or more ``date_field``-scheduled custom events, the sweeper:

  1. Figures out the org's current LOCAL hour from ``org.timezone``.
  2. Calls
     :func:`core.custom_events.service.sweep_and_fire_for_org`
     with that hour + today's local date.
  3. The service branches on system-column vs custom-field JSONB,
     matches contacts on the appropriate date grain (full date /
     month+day / day-of-month), and fires each match.

Idempotency is upheld by the partial unique index
``ux_custom_event_occ_dedup`` — the sweeper's INSERT triggers a
409 on a re-run so we can retry / re-tick safely.

Timezone handling: ``org.timezone`` is a full IANA name (e.g.
``Asia/Kolkata``). ``zoneinfo.ZoneInfo`` handles DST automatically —
during DST transitions the hour skip / repeat may cause the sweep
to run twice or not at all for one hour on the transition day. Both
paths are absorbed by the dedup index (double-run) or the following
hour's tick (skip). Documented; not a bug.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.app.core.custom_events import data_access as _da
from src.app.core.custom_events import service as _svc
from src.app.shared.db import async_session

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover — dev shells without Celery

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


async def run_hourly_sweep() -> dict[str, dict[str, int]]:
    """Pure-async entry point — the Celery task wraps this in
    ``asyncio.run``. Exposed separately so tests can drive it without
    the Celery machinery.

    Groups scheduled events by ``org_id``, resolves each org's local
    hour + local date via its ``timezone``, and delegates to the
    service sweeper. Returns per-org fire counts keyed by event_key
    for observability.
    """
    async with async_session() as session:
        events = await _da.list_all_scheduled_events(session)
        if not events:
            logger.debug("custom_events.sweep: no scheduled events; skipping")
            return {}

        # Bucket events by org so we do one timezone resolution per org
        # rather than per event.
        org_ids = sorted({e.org_id for e in events})

        # Load each org's timezone. Local import — avoids a hard
        # dependency cycle at module load.
        from src.app.core.tenants import data_access as tenants_da

        results: dict[str, dict[str, int]] = {}
        now_utc = datetime.now(UTC)
        for org_id in org_ids:
            org = await tenants_da.get_organization_by_id(session, org_id)
            if org is None:
                continue
            tz_name = getattr(org, "timezone", None) or "UTC"
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                logger.warning(
                    "custom_events.sweep: org %s has invalid timezone %r; "
                    "falling back to UTC",
                    org_id,
                    tz_name,
                )
                tz = ZoneInfo("UTC")
            local_now = now_utc.astimezone(tz)
            fires = await _svc.sweep_and_fire_for_org(
                session,
                org_id=org_id,
                org_hour_local=local_now.hour,
                today_local=local_now.date(),
            )
            if fires:
                results[str(org_id)] = fires
        return results


@_shared_task(name="src.app.core.custom_events.tasks.sweep_date_triggered_events")
def sweep_date_triggered_events() -> dict[str, dict[str, int]]:
    """Celery beat entry point. Runs hourly at :05.

    Returns per-org fire counts so operators can see recent sweep
    activity in the Celery flower / result backend without opening
    the app logs.
    """
    return asyncio.run(run_hourly_sweep())


__all__ = ["run_hourly_sweep", "sweep_date_triggered_events"]
