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
        run = await data_access.get_run_by_id_unscoped(session, run_id=uuid.UUID(run_id))
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
            # tasks/automation-engine Step 13 — send-guard
            # compliance check fires BEFORE we flip status to
            # dispatched. Marketing-category runs may be skipped
            # (DPDP / frequency cap) or deferred (quiet hours);
            # transactional + service categories short-circuit to
            # allow.
            guard_result = await _run_send_guard(session, run)
            if guard_result is not None:
                return guard_result

            run.status = AutomationRunStatus.dispatched
            run.dispatched_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(run)

            try:
                channel_message_id = await _execute_send(session, run)
            except _SkipSendError as exc:
                run.status = AutomationRunStatus.skipped
                run.error = str(exc)
                run.completed_at = datetime.now(UTC)
                await session.commit()
                return {"status": "skipped", "error": str(exc)}
            except _PermanentSendError as exc:
                run.status = AutomationRunStatus.failed
                run.error = str(exc)
                run.completed_at = datetime.now(UTC)
                await session.commit()
                return {"status": "failed", "error": str(exc)}
            run.status = AutomationRunStatus.sent
            run.channel_message_id = channel_message_id
            run.completed_at = datetime.now(UTC)
            await session.commit()
            return {"status": "sent", "channel_message_id": channel_message_id}
        finally:
            reset_context(token)


async def _run_send_guard(session, run) -> dict[str, Any] | None:
    """Run the Step-13 send-guard layer for ``run``. Returns a
    terminal status dict when the guard short-circuited the send
    (skipped or deferred), or ``None`` when the run should proceed
    to dispatch normally.

    A deferred run is re-queued via
    ``deliver_run.apply_async(args=(run_id,), eta=defer_until)``;
    the row stays ``queued`` so the next pick-up resumes the same
    code path.

    A skipped run is written terminal as ``status='skipped'`` +
    ``error=skip_reason`` so the Run-History UI surfaces the
    rejection cause to the operator.
    """
    from sqlalchemy import select as _select

    from src.app.core.automation import data_access as automation_da
    from src.app.core.automation import send_guard
    from src.app.core.automation.models import AutomationRunStatus
    from src.app.core.contacts.models import Contact
    from src.app.core.templates import data_access as templates_da
    from src.app.core.tenants.models import Organization

    trigger = await automation_da.get_trigger(session, org_id=run.org_id, trigger_id=run.trigger_id)
    if trigger is None:
        # Let the downstream _execute_send path surface the missing
        # trigger as a permanent failure — keeps error-shape in one
        # place.
        return None

    template = await templates_da.get_template(
        session, org_id=run.org_id, template_id=trigger.template_id
    )
    if template is None:
        return None

    org = (
        await session.execute(_select(Organization).where(Organization.id == run.org_id))
    ).scalar_one_or_none()
    if org is None:
        return None

    contact = None
    if run.contact_id is not None:
        contact = (
            await session.execute(_select(Contact).where(Contact.id == run.contact_id))
        ).scalar_one_or_none()

    now_utc = datetime.now(UTC)
    decision = await send_guard.evaluate(
        session,
        org=org,
        template=template,
        contact=contact,
        contact_id=run.contact_id,
        channel=str(
            trigger.channel.value if hasattr(trigger.channel, "value") else trigger.channel
        ),
        now_utc=now_utc,
    )

    if decision.allow:
        return None

    if decision.skip_reason is not None:
        run.status = AutomationRunStatus.skipped
        run.error = decision.skip_reason
        run.completed_at = now_utc
        await session.commit()
        try:
            from src.app.core import audit

            await audit.log(
                f"automations.send_blocked_{decision.skip_reason}",
                entity_type="automation_run",
                entity_id=run.id,
                after={
                    "skip_reason": decision.skip_reason,
                    "trigger_id": str(run.trigger_id),
                    "contact_id": (str(run.contact_id) if run.contact_id else None),
                },
            )
        except Exception:
            logger.exception(
                "automation.deliver_run audit_emit_failed run=%s reason=%s",
                run.id,
                decision.skip_reason,
            )
        return {"status": "skipped", "error": decision.skip_reason}

    if decision.defer_until is not None:
        # Push the run scheduled_at forward + re-queue the task so
        # the worker picks it up at the right time. Status stays
        # `queued`.
        run.scheduled_at = decision.defer_until
        await session.commit()
        try:
            deliver_run.apply_async(args=(str(run.id),), eta=decision.defer_until)
        except Exception:
            logger.exception(
                "automation.deliver_run defer_reschedule_failed run=%s",
                run.id,
            )
        try:
            from src.app.core import audit

            await audit.log(
                "automations.send_deferred_quiet_hours",
                entity_type="automation_run",
                entity_id=run.id,
                after={
                    "defer_until": decision.defer_until.isoformat(),
                    "trigger_id": str(run.trigger_id),
                },
            )
        except Exception:
            logger.exception(
                "automation.deliver_run audit_emit_failed run=%s",
                run.id,
            )
        return {
            "status": "deferred",
            "defer_until": decision.defer_until.isoformat(),
        }

    return None


class _PermanentSendError(Exception):
    """Internal sentinel — adapter failure that should NOT retry.
    Transient errors propagate out so Celery's autoretry fires."""


class _SkipSendError(Exception):
    """Internal sentinel — the send should be recorded as ``skipped``
    (not ``failed``) with the reason as the exception message. Used
    for ``org_sender_not_configured`` — the org hasn't wired an
    outbound identity yet, so we log at INFO + mark the run skipped
    instead of failing it."""


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
    )
    from src.app.core.conversations.registry import (
        resolve as resolve_adapter,
    )
    from src.app.core.templates import data_access as templates_da
    from src.app.core.templates.variables import resolve as render

    trigger = await automation_da.get_trigger(session, org_id=run.org_id, trigger_id=run.trigger_id)
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
    rendered_subject = render(template.subject, payload) if template.subject else None

    try:
        adapter = resolve_adapter(trigger.channel)
    except ChannelNotRegistered as exc:
        raise _PermanentSendError(f"channel_not_registered: {exc}") from exc

    if trigger.channel == ConversationChannel.email:
        from config import API_BASE_URL

        from src.app.core.automation.tracking import (
            inject_tracking_pixel_and_links,
        )
        from src.app.shared.email import Email
        from src.app.shared.email.org_sender import resolve_org_sender

        # Step 14 — wrap the plain-text body in a minimal HTML
        # envelope + inject the open-pixel + click-rewrites. The
        # plain-text part stays untouched so privacy-conscious
        # clients (text-only readers) get the original message
        # without any tracking artefacts.
        public_base_url = API_BASE_URL.rstrip("/")
        html_skeleton = (
            f"<html><body>"
            f'<pre style="font-family:inherit;white-space:pre-wrap">'
            f"{rendered_body}"
            f"</pre></body></html>"
        )
        body_html = inject_tracking_pixel_and_links(
            run_id=run.id,
            html_body=html_skeleton,
            public_base_url=public_base_url,
        )

        # Use the ORG's own sender identity (SMTP or OAuth) rather
        # than the platform Brevo sender — org-generated automation
        # mail must originate from the org's brand. No silent
        # fallback to Brevo; when the org hasn't configured a
        # sender, the run is marked ``skipped`` with the reason.
        backend = await resolve_org_sender(session, org_id=run.org_id)
        if backend is None:
            logger.info(
                "org_sender_not_configured run=%s org_id=%s",
                run.id,
                run.org_id,
            )
            raise _SkipSendError("org_sender_not_configured")

        await backend.send(
            Email(
                to=recipient,
                subject=rendered_subject or template.name,
                body_text=rendered_body,
                body_html=body_html,
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
    return (
        type(exc).__name__.endswith("NotConfigured")
        or type(exc).__name__.endswith("NotConnected")
        or isinstance(exc, NotImplementedError)
    )


@_shared_task(
    name="src.app.core.automation.tasks.daily_time_based_scan",
)
def daily_time_based_scan() -> dict[str, int]:
    """Beat-scheduled daily sweep — fires ``contact.birthday`` for
    today's birthdays + ``lead.stale_30d`` for every lead with no
    activity in 30 days. Delegates the actual scan + publish loop to
    :func:`core.automation.scheduler.run_daily_time_based_scan` so
    the logic stays unit-testable without a worker."""
    from src.app.core.automation.scheduler import run_daily_time_based_scan

    return asyncio.run(run_daily_time_based_scan())


__all__ = ["daily_time_based_scan", "deliver_run"]
