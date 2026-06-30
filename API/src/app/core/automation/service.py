"""Service layer for the automation engine.

CRUD over ``AutomationTrigger`` + the matcher the dispatcher (Step 4)
hits per event. Every write happens inside a single async
transaction; the service is the ONLY layer that touches commits per
the locked layered-architecture convention (manager spec
2026-06-25). The router (Step 3) is a thin shell over these
functions.

  * :func:`create_trigger` inserts the row + the channel/template
    consistency check + the duplicate-name-per-org enforcement.
  * :func:`update_trigger` PATCH-style updates. ``enabled`` is
    handled separately via :func:`enable_trigger` /
    :func:`disable_trigger` for idempotent toggle semantics — the
    Settings → Automations list page's enable-toggle hits those
    directly without re-validating the whole row.
  * :func:`delete_trigger` is hard-delete. Triggers don't carry a
    "soft archive" state — operators disable via the toggle.
    Historical run rows survive via :class:`ON DELETE CASCADE` only
    when the operator explicitly chose deletion; the operator
    pattern is "disable + keep history" via :func:`disable_trigger`.
  * :func:`match_triggers` is the dispatcher's entry point — pulls
    every enabled trigger for ``(org_id, event_type)`` from the DAL
    + filters by :func:`core.automation.conditions.evaluate`
    against the published payload. Returns matching triggers in
    deterministic id order so run rows insert in a stable sequence.

Read paths (``get_trigger`` / ``list_triggers``) defer to the DAL
+ surface :class:`TriggerNotFound` for 404 mapping.

The template-channel consistency check at create + update time:
``trigger.channel`` must equal the linked template's channel. A
WhatsApp trigger pointing at an email template would dispatch
through the wrong adapter — :class:`MissingTemplateForChannel` is
the 422 the operator sees in the trigger editor.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import conditions, data_access
from src.app.core.automation.exceptions import (
    DuplicateTriggerName,
    MissingTemplateForChannel,
    TriggerNotFound,
)
from src.app.core.automation.models import AutomationTrigger
from src.app.core.automation.schemas import TriggerCreate, TriggerUpdate
from src.app.core.conversations.models import ConversationChannel

logger = logging.getLogger(__name__)


# --- reads -----------------------------------------------------------


async def get_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    trigger_id: uuid.UUID,
) -> AutomationTrigger:
    """Resolve a trigger by id; raise :class:`TriggerNotFound` on miss
    so the router can return 404 with a structured payload."""
    row = await data_access.get_trigger(session, org_id=org_id, trigger_id=trigger_id)
    if row is None:
        raise TriggerNotFound(trigger_id)
    return row


async def list_triggers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str | None = None,
    enabled: bool | None = None,
    channel: ConversationChannel | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AutomationTrigger], int]:
    return await data_access.list_triggers(
        session,
        org_id=org_id,
        event_type=event_type,
        enabled=enabled,
        channel=channel,
        q=q,
        limit=limit,
        offset=offset,
    )


# --- writes ----------------------------------------------------------


async def create_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: TriggerCreate,
) -> AutomationTrigger:
    """Insert a new trigger row. Raises:

    * :class:`DuplicateTriggerName` if the `(org_id, lower(name))`
      pair already exists (functional unique index from Step 1
      catches it on commit; we translate the IntegrityError).
    * :class:`InvalidCondition` if the conditions JSONB is
      structurally broken (op typo, missing field, etc.).
    * :class:`MissingTemplateForChannel` if the linked template's
      channel doesn't match ``payload.channel``.
    """
    conditions.validate(payload.conditions)
    await _enforce_template_channel(
        session,
        org_id=org_id,
        template_id=payload.template_id,
        trigger_channel=payload.channel,
    )

    existing = await data_access.get_trigger_by_name(session, org_id=org_id, name=payload.name)
    if existing is not None:
        raise DuplicateTriggerName(payload.name)

    trigger = AutomationTrigger(
        org_id=org_id,
        name=payload.name.strip(),
        enabled=payload.enabled,
        event_type=payload.event_type.strip(),
        conditions=dict(payload.conditions),
        channel=payload.channel,
        template_id=payload.template_id,
        delay_seconds=payload.delay_seconds,
        recipient_resolver=payload.recipient_resolver.strip(),
        recipient_resolver_config=dict(payload.recipient_resolver_config),
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    data_access.add_trigger(session, trigger)

    try:
        await session.flush()
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Race with another concurrent insert — the functional
        # unique index is the source of truth.
        raise DuplicateTriggerName(payload.name) from exc

    await session.refresh(trigger)
    logger.info(
        "automation.create_trigger org=%s trigger=%s event=%s channel=%s",
        org_id,
        trigger.id,
        trigger.event_type,
        trigger.channel.value,
    )
    return trigger


async def update_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
) -> AutomationTrigger:
    """PATCH-style update. Only fields present on the payload are
    applied; ``enabled`` toggle still works but the dedicated
    helpers (:func:`enable_trigger` / :func:`disable_trigger`) are
    preferred for the Settings list-page toggle path."""
    trigger = await get_trigger(session, org_id=org_id, trigger_id=trigger_id)

    next_channel = payload.channel if payload.channel is not None else trigger.channel
    next_template_id = (
        payload.template_id if payload.template_id is not None else trigger.template_id
    )

    if payload.conditions is not None:
        conditions.validate(payload.conditions)

    if payload.channel is not None or payload.template_id is not None:
        await _enforce_template_channel(
            session,
            org_id=org_id,
            template_id=next_template_id,
            trigger_channel=next_channel,
        )

    if payload.name is not None and payload.name.strip().lower() != trigger.name.lower():
        clashing = await data_access.get_trigger_by_name(session, org_id=org_id, name=payload.name)
        if clashing is not None and clashing.id != trigger.id:
            raise DuplicateTriggerName(payload.name)
        trigger.name = payload.name.strip()

    if payload.event_type is not None:
        trigger.event_type = payload.event_type.strip()
    if payload.channel is not None:
        trigger.channel = payload.channel
    if payload.template_id is not None:
        trigger.template_id = payload.template_id
    if payload.enabled is not None:
        trigger.enabled = payload.enabled
    if payload.conditions is not None:
        trigger.conditions = dict(payload.conditions)
    if payload.delay_seconds is not None:
        trigger.delay_seconds = payload.delay_seconds
    if payload.recipient_resolver is not None:
        trigger.recipient_resolver = payload.recipient_resolver.strip()
    if payload.recipient_resolver_config is not None:
        trigger.recipient_resolver_config = dict(payload.recipient_resolver_config)
    trigger.updated_by_user_id = user_id

    try:
        await session.flush()
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Concurrent name conflict from a parallel rename.
        raise DuplicateTriggerName(payload.name or trigger.name) from exc

    await session.refresh(trigger)
    logger.info("automation.update_trigger org=%s trigger=%s", org_id, trigger.id)
    return trigger


async def enable_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    trigger_id: uuid.UUID,
) -> AutomationTrigger:
    """Idempotent enable. Returns the trigger row regardless of
    whether the toggle actually flipped a bit."""
    return await _set_enabled(
        session,
        org_id=org_id,
        user_id=user_id,
        trigger_id=trigger_id,
        enabled=True,
    )


async def disable_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    trigger_id: uuid.UUID,
) -> AutomationTrigger:
    """Idempotent disable."""
    return await _set_enabled(
        session,
        org_id=org_id,
        user_id=user_id,
        trigger_id=trigger_id,
        enabled=False,
    )


async def delete_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    trigger_id: uuid.UUID,
) -> None:
    """Hard delete. ON DELETE CASCADE on ``tbl_automation_runs``
    drops historical runs — operators usually prefer
    :func:`disable_trigger` to preserve audit history."""
    trigger = await get_trigger(session, org_id=org_id, trigger_id=trigger_id)
    await session.delete(trigger)
    await session.commit()
    logger.info("automation.delete_trigger org=%s trigger=%s", org_id, trigger_id)


# --- matcher --------------------------------------------------------


async def match_triggers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> list[AutomationTrigger]:
    """The dispatcher's entry point. Returns every enabled trigger
    for ``(org_id, event_type)`` whose conditions evaluate true
    against ``payload``. Deterministic id ordering."""
    candidates = await data_access.match_enabled_triggers(
        session, org_id=org_id, event_type=event_type
    )
    matches: list[AutomationTrigger] = []
    for trigger in candidates:
        if conditions.evaluate(trigger.conditions, payload):
            matches.append(trigger)
    return matches


# --- helpers --------------------------------------------------------


async def _enforce_template_channel(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    trigger_channel: ConversationChannel,
) -> None:
    """Confirm the linked template exists in this org + its channel
    matches the trigger's. Raises
    :class:`MissingTemplateForChannel` on mismatch (router maps to
    422). A missing template id is also surfaced as channel mismatch
    so the operator sees one clear error."""
    from src.app.core.templates import data_access as templates_da

    template = await templates_da.get_template(session, org_id=org_id, template_id=template_id)
    if template is None:
        raise MissingTemplateForChannel(
            trigger_channel=trigger_channel.value,
            template_channel="(template missing)",
        )
    if template.channel != trigger_channel:
        raise MissingTemplateForChannel(
            trigger_channel=trigger_channel.value,
            template_channel=template.channel.value,
        )


async def _set_enabled(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    trigger_id: uuid.UUID,
    enabled: bool,
) -> AutomationTrigger:
    trigger = await get_trigger(session, org_id=org_id, trigger_id=trigger_id)
    if trigger.enabled == enabled:
        return trigger
    trigger.enabled = enabled
    trigger.updated_by_user_id = user_id
    await session.commit()
    await session.refresh(trigger)
    logger.info(
        "automation.set_enabled org=%s trigger=%s enabled=%s",
        org_id,
        trigger.id,
        enabled,
    )
    return trigger


__all__ = [
    "create_trigger",
    "delete_trigger",
    "disable_trigger",
    "enable_trigger",
    "get_trigger",
    "list_triggers",
    "match_triggers",
    "update_trigger",
]
