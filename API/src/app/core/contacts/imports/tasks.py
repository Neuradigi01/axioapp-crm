"""Celery task that drives a contact bulk import end-to-end.

Mirror of ``src/app/core/leads/imports/tasks.py`` — kept intentionally
symmetric so behaviour drift between the two import surfaces gets
caught on code review.

`process_contact_import(import_id, org_id, user_id, create_group,
group_name)` is enqueued by the commit endpoint. It:

  1. Claims the row (`ContactImportStatus.processing`), or exits
     early if another worker already terminal-transitioned it
     (idempotent — Celery retries land cleanly).
  2. Runs ``_run_commit`` in ``service.py`` under a fresh async
     session — same row-loop the sync/dev branch uses.
  3. Persists ``committed`` on success, ``failed`` on catastrophe.

Celery workers are synchronous, so the entrypoint bridges to async
via ``asyncio.run(...)`` — same pattern the leads pipeline uses.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery not always installed in dev
    HAS_CELERY = False

    # Fallback shim so the module imports cleanly without celery. Call
    # sites that need the task to run synchronously (dev, tests) await
    # ``process_contact_import_async(...)`` directly — see
    # ``commit_import`` in service.py for the branching.
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

        if decorator_args and callable(decorator_args[0]) and not decorator_kwargs:
            return _wrap(decorator_args[0])
        return _wrap


from sqlalchemy import select

from src.app.core.contacts.imports.models import ContactImport, ContactImportStatus
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = {
    ContactImportStatus.committed,
    ContactImportStatus.failed,
    ContactImportStatus.cancelled,
}


@_shared_task(name="src.app.core.contacts.imports.tasks.process_contact_import")
def process_contact_import(
    import_id: str,
    org_id: str,
    user_id: str,
    create_group: bool,
    group_name: str | None,
) -> dict[str, Any]:
    """Celery entrypoint (sync). Bridges into the async body via
    ``asyncio.run(...)`` — Celery workers run with no event loop of
    their own. Dev call sites (``HAS_CELERY == False``) skip this and
    await ``process_contact_import_async(...)`` directly.
    """
    return asyncio.run(
        process_contact_import_async(
            uuid.UUID(import_id),
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            create_group,
            group_name,
        )
    )


async def process_contact_import_async(
    import_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    create_group: bool,
    group_name: str | None,
) -> dict[str, Any]:
    """Async worker body — claim the row, run the commit loop, persist
    outcome. Idempotent: no-op if the row is already terminal, and
    honours a ``cancelled`` status set by the operator before we
    started."""
    # Set tenant context so RLS authorises the worker's queries + audit
    # events derive the correct org/actor without explicit kwargs.
    token = set_context(RequestContext(org_id=org_id, user_id=user_id))
    try:
        # Pre-flight — refuse to run if the row is missing, terminal,
        # or wasn't left in `processing` by the commit endpoint.
        async with async_session() as session:
            row = (
                await session.execute(select(ContactImport).where(ContactImport.id == import_id))
            ).scalar_one_or_none()
            if row is None:
                logger.warning("process_contact_import: %s not found", import_id)
                return {"status": "missing"}
            if row.status in _TERMINAL_STATUSES:
                logger.info(
                    "process_contact_import: %s already %s — no-op",
                    import_id,
                    row.status.value,
                )
                return {"status": row.status.value}
            if row.status != ContactImportStatus.processing:
                logger.info(
                    "process_contact_import: %s in %s — refusing to run",
                    import_id,
                    row.status.value,
                )
                return {"status": row.status.value}

        # Run the row loop in its own session so a rollback here
        # doesn't clobber the pre-flight session. `_run_commit` handles
        # transitions to `committed` / `failed` internally.
        # Local import breaks a circular dependency (service.py imports
        # this module for dispatch).
        from src.app.core.contacts.imports.service import _run_commit

        try:
            async with async_session() as session:
                await _run_commit(
                    session,
                    import_id=import_id,
                    org_id=org_id,
                    user_id=user_id,
                    create_group=create_group,
                    group_name=group_name,
                )
            return {"status": "completed"}
        except Exception as exc:  # pragma: no cover - guard for celery visibility
            logger.exception("process_contact_import: commit failed for %s", import_id)
            async with async_session() as session:
                fail_row = (
                    await session.execute(
                        select(ContactImport).where(ContactImport.id == import_id)
                    )
                ).scalar_one_or_none()
                if fail_row is not None and fail_row.status not in _TERMINAL_STATUSES:
                    fail_row.status = ContactImportStatus.failed
                    await session.commit()
            raise exc
    finally:
        reset_context(token)


__all__ = [
    "HAS_CELERY",
    "process_contact_import",
    "process_contact_import_async",
]
