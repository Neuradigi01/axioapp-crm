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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import conditions, data_access, enum_resolvers, event_catalog
from src.app.core.automation.enum_resolvers import EnumOption
from src.app.core.automation.exceptions import (
    DuplicateTriggerName,
    FieldNotEnum,
    FieldNotFound,
    MissingTemplateForChannel,
    ResolverNotRegistered,
    TriggerNotFound,
)
from src.app.core.automation.field_specs import FieldType
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


# --- tasks/automation-conditions/ Step 2 ----------------------------


async def list_field_values(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    field: str,
) -> list[EnumOption]:
    """Return the caller org's live options for one enum-typed field
    on one event.

    Backs the ``POST /event-types/{event}/field-values`` endpoint.
    Raises:
      * :class:`event_catalog.get_entry` returning ``None`` → caller
        (router) maps to a 404 ``event_not_found`` — no exception here
        because the router already has a clean way to signal it via
        the endpoint's path resolution.
      * :class:`FieldNotFound` when ``field`` isn't in the event's
        ``condition_fields`` → 404.
      * :class:`FieldNotEnum` when the matched field's type isn't
        ``enum`` → 422 (e.g. customer picked a currency or text field).
      * :class:`ResolverNotRegistered` when the field's
        ``enum_resolver`` key has no registered callable → 500 (code
        bug; pin-test catches it before deploy).

    Zero-rows is NOT an error — the frontend renders a "no options
    configured — set them up under Settings → …" hint on ``[]``.
    """
    entry = event_catalog.get_entry(event_type)
    if entry is None:
        # Signalled by the router via a path-level 404 before this
        # call in practice — but service-layer guard keeps the
        # function safe if called directly (dispatcher, tests, etc.).
        raise FieldNotFound(event_type=event_type, field=field)

    spec = next((s for s in entry.condition_fields if s.path == field), None)
    if spec is None:
        raise FieldNotFound(event_type=event_type, field=field)

    if spec.type is not FieldType.enum:
        raise FieldNotEnum(
            event_type=event_type,
            field=field,
            field_type=spec.type.value,
        )

    # FieldSpec.__post_init__ guarantees enum_resolver is set when
    # type is enum, so this cast is safe.
    resolver_key = spec.enum_resolver
    assert resolver_key is not None
    resolver = enum_resolvers.get_resolver(resolver_key)
    if resolver is None:
        raise ResolverNotRegistered(resolver_key)

    return await resolver(session, org_id)


async def preview_matches(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    conditions_ast: dict[str, Any],
    window_days: int = 7,
) -> dict[str, Any]:
    """Count historical events in the last ``window_days`` that would
    match the customer's draft ``conditions`` if it were saved as an
    automation trigger (``tasks/automation-conditions/`` Step 5).

    Reads from ``tbl_automation_runs.event_payload`` — cheapest data
    source, already indexed. Runs the SAME
    :func:`core.automation.conditions.evaluate` the live dispatcher
    uses, so preview numbers match reality once the trigger goes
    live. No side effects, no writes.

    Raises :class:`~core.automation.exceptions.InvalidCondition` if
    the AST is structurally broken — the router surfaces that as a
    422 so the customer sees the shape complaint immediately (no
    silent 0-match, which would look like "your filter is wrong").

    Returns a dict matching :class:`PreviewMatchesResponse`:

    * ``matched`` — count of payloads that satisfy the AST.
    * ``scanned`` — total payloads considered (may be less than the
      window's true event count if truncated).
    * ``window_days`` — echoed back for the frontend to display.
    * ``source`` — ``'runs'`` when we read from the runs table,
      ``'none'`` when the org has zero runs in the window (so the
      frontend can render a "no historical events available" hint
      rather than a misleading "matched 0").
    * ``truncated`` — ``True`` when the row cap fired and the real
      total is at least ``scanned``.

    Note on undercount: a brand-new event type with no active triggers
    yet has no rows in ``tbl_automation_runs`` and reports
    ``source='none'``, even if the publisher is emitting the event.
    Audit-log fallback is a future step (see step-5 MD "Out of scope"
    — deferred until ``tasks/audit-log/`` lands with a stable
    ``tbl_audit_log`` shape).
    """
    # Validate the AST up-front so the customer sees a structural
    # error instead of a "we couldn't compute your preview" mystery.
    conditions.validate(conditions_ast)

    # Fast-path 404: caller (router) already checks the catalog but
    # a service-level guard keeps this function safe when called
    # from tests / scripts.
    if event_catalog.get_entry(event_type) is None:
        return {
            "matched": 0,
            "scanned": 0,
            "window_days": window_days,
            "source": "none",
            "truncated": False,
        }

    since = datetime.now(UTC) - timedelta(days=window_days)
    # limit=501 → we scan 501 rows and know the true total is >500
    # if the last one comes back. Row-cap is a soft DoS defense —
    # 500 payloads through the evaluator take milliseconds; more
    # would still work, but we'd rather report "at least 500" than
    # spend budget on an unbounded scan.
    payloads = await data_access.list_recent_event_payloads(
        session,
        org_id=org_id,
        event_type=event_type,
        since=since,
        limit=501,
    )
    if not payloads:
        return {
            "matched": 0,
            "scanned": 0,
            "window_days": window_days,
            "source": "none",
            "truncated": False,
        }

    truncated = len(payloads) > 500
    to_scan = payloads[:500] if truncated else payloads
    matched = sum(1 for p in to_scan if conditions.evaluate(conditions_ast, p))
    return {
        "matched": matched,
        "scanned": len(to_scan),
        "window_days": window_days,
        "source": "runs",
        "truncated": truncated,
    }


__all__ = [
    "create_trigger",
    "delete_trigger",
    "disable_trigger",
    "enable_trigger",
    "get_trigger",
    "list_field_values",
    "list_triggers",
    "match_triggers",
    "preview_matches",
    "update_trigger",
]
