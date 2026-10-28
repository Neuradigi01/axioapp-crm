"""Celery tasks for the core billing module.

One beat-scheduled task today — :func:`scan_for_overdue` — sweeps
``tbl_invoices`` once a day and publishes ``invoice.overdue_7d`` for
every ``issued`` invoice whose ``issued_at`` is more than 7 days
ago. The dispatcher's ``(trigger_id, event_id)`` uniqueness index on
``tbl_automation_runs`` absorbs daily-tick overlap so each invoice
gets at most one overdue-reminder fire — the deterministic
``event_id=f"invoice_overdue_7d:{invoice_id}"`` ensures replays of
the scan never produce duplicate runs.

Convention: ``@shared_task`` wrappers call ``asyncio.run(_async_helper(...))``
per ``src/celery/worker.py``'s engine-reset hooks. Don't write
``async def`` tasks — they cannot be called as ``.delay()`` and the
prefork worker can't drive them.

Mirrors the celery-absent shim shape of ``core.automation.tasks`` /
``core.appointments.tasks`` so dev shells without Celery installed
don't break import.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC
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


# Default overdue threshold. The seeded "Invoice Overdue 7d" trigger
# binds to the ``invoice.overdue_7d`` event_type so changing this
# constant means the publisher + the seeded trigger event_type must
# move together. Future variations (14d / 30d) would land as
# additional events.
_OVERDUE_DAYS = 7


@_shared_task(
    name="src.app.core.billing.tasks.scan_for_overdue",
)
def scan_for_overdue() -> dict[str, Any]:
    """Beat-scheduled sweep — fires ``invoice.overdue_7d`` for every
    ``issued`` invoice older than 7 days. Returns a small summary
    ``{found, published}`` for the worker logs."""
    return asyncio.run(_scan_for_overdue_async())


async def _scan_for_overdue_async() -> dict[str, Any]:
    from src.app.core.billing import data_access as _da
    from src.app.shared.db import async_session

    published = 0

    async with async_session() as session:
        overdue = await _da.find_overdue(session, days_overdue=_OVERDUE_DAYS)
        for inv in overdue:
            ok = await _publish_overdue(session, inv=inv)
            if ok:
                published += 1

    logger.info(
        "billing.scan_for_overdue done found=%d published=%d",
        len(overdue),
        published,
    )
    return {"found": len(overdue), "published": published}


async def _publish_overdue(session, *, inv) -> bool:
    """Build the ``invoice.overdue_7d`` envelope + publish via the
    bus. Sets a request context for the dispatcher subscriber so its
    session opens with the right tenant scope; returns True when the
    publish completed (subscriber outcomes are absorbed by the bus +
    logged)."""
    try:
        from datetime import datetime

        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization
        from src.app.shared.context import (
            RequestContext,
            reset_context,
            set_context,
        )

        contact = None
        if inv.contact_id is not None:
            contact = (
                await session.execute(_select(Contact).where(Contact.id == inv.contact_id))
            ).scalar_one_or_none()
        org = (
            await session.execute(_select(Organization).where(Organization.id == inv.org_id))
        ).scalar_one_or_none()

        days_overdue = None
        if inv.issued_at is not None:
            delta = datetime.now(UTC) - inv.issued_at
            days_overdue = delta.days

        payload: dict[str, Any] = {
            "invoice_id": str(inv.id),
            "contact_id": (str(inv.contact_id) if inv.contact_id else None),
            "total_amount": str(inv.total),
            "currency": inv.currency,
            "issued_at": (inv.issued_at.isoformat() if inv.issued_at else None),
            "days_overdue": days_overdue,
            "invoice": {
                "id": str(inv.id),
                "number": inv.number,
                "total_amount": str(inv.total),
                "currency": inv.currency,
                "issued_at": (inv.issued_at.isoformat() if inv.issued_at else None),
            },
        }
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        token = set_context(RequestContext(org_id=inv.org_id, user_id=None))
        try:
            await events_publish(
                "invoice.overdue_7d",
                payload,
                org_id=inv.org_id,
                event_id=f"invoice_overdue_7d:{inv.id}",
            )
        finally:
            reset_context(token)
        return True
    except Exception:
        logger.exception(
            "billing.scan_for_overdue publish_failed invoice=%s",
            getattr(inv, "id", None),
        )
        return False


__all__ = ["scan_for_overdue"]
