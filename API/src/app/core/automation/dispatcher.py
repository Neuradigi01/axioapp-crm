"""Automation dispatcher — bus → match → Celery pipeline.

The wildcard subscriber registered at app start (:mod:`core.automation`)
funnels every published event into :func:`dispatch_event`. For each
matched trigger the dispatcher:

1. Looks up the prior run by ``(trigger_id, event_id)`` and
   short-circuits when a row already exists — absorbs at-least-once
   replays cleanly. Backed by the unique partial index from
   migration 0128.
2. Resolves the recipient via
   :func:`core.automation.recipients.resolve` against the
   trigger's ``recipient_resolver`` + payload. ``None`` lands a
   ``skipped`` audit row with ``error='no_recipient'`` so the
   run-history UI shows the operator the reason.
3. Inserts a ``tbl_automation_runs`` row in ``status='queued'`` with
   ``scheduled_at = now() + trigger.delay_seconds``.
4. Hands the run id to :mod:`core.automation.tasks` via Celery's
   ``apply_async(countdown=...)``. The Celery task does the actual
   render + adapter dispatch + status update.

This module is the only layer that commits the queued run row.
The Celery task in :mod:`core.automation.tasks` commits the
status-update writes. Per the locked layered convention the
dispatcher is part of the service surface (orchestration +
transactions); the DAL stays pure CRUD.

Compliance gates (frequency cap, quiet hours, opt-out) are wired in
Step 13 inside this dispatcher's pre-flight. Step 4 ships the bare
queue-and-schedule path; Step 13 inserts the gate before the run
row insert (gated sends still get an audit row with
``status='skipped'`` so the operator sees the decision).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import data_access, recipients
from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.automation.service import match_triggers

logger = logging.getLogger(__name__)


async def dispatch_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    event_id: str,
) -> list[AutomationRun]:
    """Walk every enabled trigger matching ``event_type`` against
    ``payload`` and queue a send per trigger. Returns the list of
    run rows the dispatcher persisted (queued + skipped); empty
    when no triggers match.

    Idempotent on ``(trigger_id, event_id)`` — a replayed event
    never creates a second run row."""
    matches = await match_triggers(session, org_id=org_id, event_type=event_type, payload=payload)
    if not matches:
        return []

    persisted: list[AutomationRun] = []
    for trigger in matches:
        existing = await data_access.find_run_by_event_id(
            session, trigger_id=trigger.id, event_id=event_id
        )
        if existing is not None:
            logger.info(
                "automation.dispatch idempotent_skip trigger=%s event_id=%s",
                trigger.id,
                event_id,
            )
            continue

        recipient = await _resolve_recipient(session, trigger=trigger, payload=payload)
        contact_id = _extract_contact_id(payload)

        run = AutomationRun(
            org_id=org_id,
            trigger_id=trigger.id,
            event_id=event_id,
            event_payload=payload,
            contact_id=contact_id,
            scheduled_at=datetime.now(UTC) + timedelta(seconds=trigger.delay_seconds),
        )

        if recipient is None:
            run.status = AutomationRunStatus.skipped
            run.error = "no_recipient"
            run.completed_at = datetime.now(UTC)
        else:
            run.status = AutomationRunStatus.queued
            # The resolved recipient lives on the event_payload so
            # the Celery task can reuse it without re-resolving (the
            # contact row may have changed mid-delay, but the
            # operator's intent at fire time is what matters).
            run.event_payload = {
                **payload,
                "_resolved_recipient": recipient,
            }

        data_access.add_run(session, run)
        try:
            await session.flush()
            await session.commit()
        except IntegrityError:
            # Concurrent dispatcher won the race on the same
            # (trigger_id, event_id) — re-read + treat as the dedupe
            # case. Mirrors the unique-name fallback in
            # service.create_trigger.
            await session.rollback()
            duplicate = await data_access.find_run_by_event_id(
                session, trigger_id=trigger.id, event_id=event_id
            )
            if duplicate is not None:
                logger.info(
                    "automation.dispatch race_lost trigger=%s event_id=%s",
                    trigger.id,
                    event_id,
                )
                continue
            raise
        await session.refresh(run)
        persisted.append(run)

        if run.status == AutomationRunStatus.queued:
            _schedule_delivery(run)

    return persisted


# --- helpers --------------------------------------------------------


async def _resolve_recipient(
    session: AsyncSession,
    *,
    trigger: AutomationTrigger,
    payload: dict[str, Any],
) -> str | None:
    """Wrapper around the resolver registry that maps unknown
    resolvers to ``None`` (no crash) + logs once. The recipient
    resolver string is operator-supplied via the trigger editor; a
    typo there shouldn't take down the dispatcher."""
    try:
        return await recipients.resolve(
            trigger.recipient_resolver,
            session,
            payload=payload,
            config=trigger.recipient_resolver_config or {},
        )
    except recipients.UnknownResolver:
        logger.warning(
            "automation.dispatch unknown_resolver trigger=%s resolver=%s",
            trigger.id,
            trigger.recipient_resolver,
        )
        return None


def _extract_contact_id(payload: dict[str, Any]) -> uuid.UUID | None:
    """Pull ``contact_id`` (or ``contact.id``) from the payload so
    the run row preserves the audit link even after the recipient
    string is rendered down to an email/phone."""
    raw = payload.get("contact_id")
    if raw is None:
        contact = payload.get("contact")
        if isinstance(contact, dict):
            raw = contact.get("id")
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None
    return None


def _schedule_delivery(run: AutomationRun) -> None:
    """Hand the run id to Celery. ``countdown`` honors the
    trigger's ``delay_seconds``. The task itself loads the run
    + trigger + template inside its own transaction.

    The import is deferred so this module doesn't fail to load in
    contexts where Celery isn't installed (pytest, dev shells —
    the tasks module ships a shim factory)."""
    from src.app.core.automation import tasks as automation_tasks

    delay = (run.scheduled_at - datetime.now(UTC)).total_seconds()
    countdown = max(0, int(delay))
    automation_tasks.deliver_run.apply_async(
        args=(str(run.id),),
        countdown=countdown,
    )
    logger.info("automation.dispatch scheduled run=%s countdown=%ss", run.id, countdown)


# --- subscriber registration ----------------------------------------


async def _bus_subscriber(envelope: dict[str, Any]) -> None:
    """Wildcard subscriber the package init registers. Adapts the
    bus envelope shape into :func:`dispatch_event`'s signature +
    opens its own DB session so the publisher's transaction isn't
    held while we walk + queue triggers."""
    event_type = envelope.get("event_type")
    org_id = envelope.get("org_id")
    event_id = envelope.get("event_id")
    if not isinstance(event_type, str) or not isinstance(event_id, str):
        return
    if not isinstance(org_id, uuid.UUID):
        if isinstance(org_id, str):
            try:
                org_id = uuid.UUID(org_id)
            except ValueError:
                return
        else:
            return

    payload = {k: v for k, v in envelope.items() if k not in ("event_type", "org_id", "event_id")}

    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            await dispatch_event(
                session,
                org_id=org_id,
                event_type=event_type,
                payload=payload,
                event_id=event_id,
            )
    finally:
        reset_context(token)


def register_bus_subscriber() -> None:
    """Register :func:`_bus_subscriber` against the event bus as a
    wildcard. Called by :mod:`core.automation.__init__` at module
    import — the same side-effect pattern conversations adapters
    use."""
    from src.app.core.events.bus import subscribe_all

    subscribe_all(_bus_subscriber)


__all__ = ["dispatch_event", "register_bus_subscriber"]
