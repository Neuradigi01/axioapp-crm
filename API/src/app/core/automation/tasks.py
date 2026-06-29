"""Celery tasks for the automation engine.

One task today — :func:`deliver_run` — picks a queued run off the
broker, renders the linked template, dispatches via the channel
adapter, and writes back the terminal status. Step 13 will add a
periodic sweep task; Step 14 a bounce-webhook processor.

Mirrors the celery-absent shim shape of
:mod:`core.integrations.whatsapp.health_tasks` so dev shells
without Celery installed don't break import — the shim's
``apply_async`` is a no-op so the dispatcher's
``automation_tasks.deliver_run.apply_async(...)`` call still
compiles + tests can mock-patch the dispatch.

Retry policy:
  * Adapter raises a transient error class (timeout, 5xx, rate
    limit) → re-raise via ``self.retry(...)`` with exponential
    backoff; max 3 attempts.
  * Permanent error (invalid recipient, suppressed, template
    archived) → final status ``failed`` + ``error`` populated; no
    retry.
  * Recipient resolver returned ``None`` → caught by the
    dispatcher before the task is queued, so this task never sees
    a missing recipient on first attempt.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
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


# Transient adapter errors that justify a retry. Concrete adapter
# stubs raise the matching ``*NotConfigured`` exceptions (e.g.
# ``SMSNotConfigured``); those are permanent (no transport wired),
# NOT transient. Network / 5xx / rate-limit exceptions are
# adapter-specific — Step 4 catches the broad ``ConnectionError``
# +  ``TimeoutError`` here; later adapter steps can layer in their
# own typed transients.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)


@_shared_task(
    bind=True,
    name="src.app.core.automation.tasks.deliver_run",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=_TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def deliver_run(self, run_id: str) -> dict[str, Any]:
    """Render the run's template + ship via the channel adapter.

    Returns a small status dict for the worker logs. Updates the
    ``tbl_automation_runs`` row's status / dispatched_at /
    completed_at / channel_message_id / error in a single async
    transaction.
    """
    return asyncio.run(_deliver_run_async(run_id))


async def _deliver_run_async(run_id: str) -> dict[str, Any]:
    from src.app.core.automation import data_access
    from src.app.core.automation.models import AutomationRunStatus
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    async with async_session() as session:
        run = await data_access.get_run_by_id_unscoped(
            session, run_id=uuid.UUID(run_id)
        )
        if run is None:
            logger.warning("automation.deliver_run missing_run run_id=%s", run_id)
            return {"status": "missing"}
        if run.status not in (AutomationRunStatus.queued,):
            # Already dispatched or terminal — defensive against
            # Celery double-delivery.
            logger.info(
                "automation.deliver_run already_processed run=%s status=%s",
                run.id,
                run.status.value,
            )
            return {"status": run.status.value}

        org_id = run.org_id
        token = set_context(RequestContext(org_id=org_id, user_id=None))
        try:
            run.status = AutomationRunStatus.dispatched
            run.dispatched_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(run)

            try:
                channel_message_id = await _execute_send(session, run)
            except _PermanentSendError as exc:
                run.status = AutomationRunStatus.failed
                run.error = str(exc)
                run.completed_at = datetime.now(timezone.utc)
                await session.commit()
                return {"status": "failed", "error": str(exc)}
            run.status = AutomationRunStatus.sent
            run.channel_message_id = channel_message_id
            run.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"status": "sent", "channel_message_id": channel_message_id}
        finally:
            reset_context(token)


class _PermanentSendError(Exception):
    """Internal sentinel — adapter failure that should NOT retry.
    Transient errors propagate out so Celery's autoretry fires."""


async def _execute_send(session, run) -> str | None:
    """Resolve trigger + template + adapter and ship the message.
    Returns the channel-adapter's ``channel_message_id`` (or
    ``None`` when the adapter doesn't surface one — common for
    SMTP).

    Wraps adapter errors:
      * Recognised adapter ``*NotConfigured`` exceptions (no
        transport wired yet) → permanent failure.
      * Template / trigger missing → permanent failure.
      * Everything else (ConnectionError, TimeoutError, …) →
        re-raised so Celery's autoretry-for-transient policy catches.
    """
    from src.app.core.automation import data_access as automation_da
    from src.app.core.conversations.models import ConversationChannel
    from src.app.core.conversations.registry import (
        ChannelNotRegistered,
        resolve as resolve_adapter,
    )
    from src.app.core.templates import data_access as templates_da
    from src.app.core.templates.variables import resolve as render

    trigger = await automation_da.get_trigger(
        session, org_id=run.org_id, trigger_id=run.trigger_id
    )
    if trigger is None:
        raise _PermanentSendError("trigger missing")

    template = await templates_da.get_template(
        session, org_id=run.org_id, template_id=trigger.template_id
    )
    if template is None:
        raise _PermanentSendError("template missing")

    payload = run.event_payload or {}
    recipient = payload.get("_resolved_recipient")
    if not isinstance(recipient, str) or not recipient:
        raise _PermanentSendError("no_recipient_at_dispatch")

    rendered_body = render(template.body_text, payload)
    rendered_subject = (
        render(template.subject, payload) if template.subject else None
    )

    try:
        adapter = resolve_adapter(trigger.channel)
    except ChannelNotRegistered as exc:
        raise _PermanentSendError(f"channel_not_registered: {exc}") from exc

    if trigger.channel == ConversationChannel.email:
        from src.app.shared.email import Email, get_email_backend

        backend = get_email_backend()
        await backend.send(
            Email(
                to=recipient,
                subject=rendered_subject or template.name,
                body_text=rendered_body,
                body_html=None,
            )
        )
        return None

    try:
        ref = await adapter.send(
            org_id=run.org_id,
            external_id=recipient,
            text=rendered_body,
            attachments=[],
        )
    except Exception as exc:
        if _is_permanent_adapter_error(exc):
            raise _PermanentSendError(str(exc)) from exc
        raise

    return getattr(ref, "channel_message_id", None)


def _is_permanent_adapter_error(exc: BaseException) -> bool:
    """The channel-adapter stubs ship typed ``*NotConfigured``
    exceptions whose names end in ``NotConfigured`` — those are
    permanent (no transport wired). Anything else falls through to
    Celery's autoretry policy."""
    return type(exc).__name__.endswith("NotConfigured") or type(
        exc
    ).__name__.endswith("NotConnected") or isinstance(exc, NotImplementedError)


__all__ = ["deliver_run"]
