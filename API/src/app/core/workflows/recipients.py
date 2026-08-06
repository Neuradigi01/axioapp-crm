"""Recipient resolver registry for workflow Send actions.

A Send node carries ``config.recipient`` which is either a plain
string identifying the resolver (``"contact.email"``) or a dict
``{"kind": "custom", ...config}`` for resolvers that need their
own config. Resolvers read params via :func:`_recipient_params`,
which returns ``{}`` for the string form so ``.get(...)`` works
uniformly across both shapes.

Four built-in resolvers, each keyed by string:

  * ``contact.email`` / ``contact.phone`` — pulls from the run's
    ``contact_id``-linked Contact row. The Step-4 engine
    pre-hydrates the contact into ``context['contact']`` so the
    resolver hits the dict first + falls back to a DB lookup when
    the dict is missing (e.g. when contact_id was set but the
    contact has been deleted since enrolment).
  * ``user.email`` — looks up a user by id. The node config can
    supply ``user_id``; otherwise we fall back to the workflow's
    creator (``workflow.created_by_user_id``).
  * ``lead.owner`` — pulls the assigned user off the lead row + then
    that user's email or phone per ``config.method``.
  * ``custom`` — walks ``config.path`` as a dot-path against the
    trigger payload. Depth-capped at 10 segments + each segment
    limited to a 64-char identifier so a pathological config can't
    chew through memory.

Resolvers return ``None`` when the address can't be derived — the
calling Send handler then ``ActionResult(skip_reason='recipient_not_found')``
so the operator sees the failure on Step 19's run-history view.

The registry is the same shape as
:mod:`core.conversations.registry` — module-level dict, lookup by
string, raise :class:`UnknownResolver` when the key is unknown so a
typo in the workflow node config doesn't silently send nowhere.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Hard caps to defend against pathological custom-resolver configs.
_MAX_PATH_DEPTH = 10
_MAX_SEGMENT_LEN = 64
_MAX_RESOLVED_LEN = 320  # email's RFC 5321 max is 254; pad for phones / URLs.


class UnknownResolver(Exception):
    """Raised when the resolver kind isn't in the registry. The
    Send handler catches this + returns ``ActionResult(skip_reason=
    'unknown_resolver')`` so the run-history view shows the typo."""

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown recipient resolver {name!r}")
        self.name = name


#: Resolver signature — coroutine returning the address string or None.
Resolver = Callable[..., Awaitable[str | None]]


_resolvers: dict[str, Resolver] = {}


def register_resolver(name: str, resolver: Resolver) -> None:
    """Idempotent on ``(name, resolver)`` — re-registering the same
    pair is a no-op so side-effect imports don't double-add."""
    existing = _resolvers.get(name)
    if existing is resolver:
        return
    _resolvers[name] = resolver


def is_registered(name: str) -> bool:
    return name in _resolvers


def list_registered() -> list[str]:
    return sorted(_resolvers.keys())


async def resolve(
    name: str,
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    """Look up + invoke a resolver. Raises :class:`UnknownResolver`
    for unregistered names — the Send handler catches + maps to a
    skipped step."""
    fn = _resolvers.get(name)
    if fn is None:
        raise UnknownResolver(name)
    return await fn(session, run=run, node=node, context=context)


# --- Built-in resolvers --------------------------------------------------


def _recipient_params(node: dict[str, Any]) -> dict[str, Any]:
    """Normalise ``node.config.recipient`` to a params dict.

    The UI writes ``recipient`` in one of two shapes:
      * plain string — kind only, no extra params (``"lead.owner"``)
      * dict — kind + resolver params (``{"kind": "lead.owner", "method": "email"}``)

    Resolvers only care about the params half. Return ``{}`` for the
    string form so ``params.get("method", "email")`` works uniformly.
    """
    raw = (node.get("config") or {}).get("recipient")
    if isinstance(raw, dict):
        return raw
    return {}


async def _contact_email(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    """Read ``contact.email`` from the hydrated context dict first
    (set by the engine in ``_build_handler_context``); fall back
    to a direct lookup by ``run.contact_id`` so deleted-contact
    edge cases surface cleanly."""
    contact = context.get("contact")
    if isinstance(contact, dict):
        email = contact.get("email")
        if isinstance(email, str) and email.strip():
            return _trim(email)
    if run is not None and run.contact_id is not None:
        return await _lookup_contact_field(session, run.contact_id, "email")
    return None


async def _contact_phone(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    contact = context.get("contact")
    if isinstance(contact, dict):
        phone = contact.get("phone")
        if isinstance(phone, str) and phone.strip():
            return _trim(phone)
    if run is not None and run.contact_id is not None:
        return await _lookup_contact_field(session, run.contact_id, "phone")
    return None


async def _user_email(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    """Look up the email of a user. The node config can supply an
    explicit ``user_id`` (for "notify deal owner" patterns);
    otherwise we fall back to the workflow's creator."""
    params = _recipient_params(node)
    user_id_raw = params.get("user_id")
    user_uuid: uuid.UUID | None = _coerce_uuid(user_id_raw)

    # Fall back to the workflow creator. We have to look it up via
    # the run because the engine doesn't hydrate the workflow into
    # the context.
    if user_uuid is None and run is not None:
        from src.app.core.workflows import data_access as _wf_da

        workflow = await _wf_da.get_workflow(
            session, org_id=run.org_id, workflow_id=run.workflow_id
        )
        if workflow is not None:
            user_uuid = workflow.created_by_user_id

    if user_uuid is None:
        return None
    return await _lookup_user_email(session, user_uuid)


async def _lead_owner(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    """Resolve the lead's assigned user, then that user's email or
    phone per ``config.method`` (defaults to ``email``).

    Resolution order:
      1. ``trigger_payload.lead.assigned_to_id`` snapshot (event-triggered
         runs like ``lead.assigned`` embed it).
      2. ``trigger_payload.lead_id`` / ``trigger_payload.lead.id`` → DB
         lookup on ``tbl_leads.assigned_to_id``.
      3. ``run.contact_id`` → most-recent lead for that contact →
         ``assigned_to_id``. This is the fallback for schedule-triggered
         runs that carry a contact but no lead snapshot.
    """
    params = _recipient_params(node)
    method = params.get("method", "email")
    if method not in ("email", "phone"):
        return None

    # 1) Assignee snapshot embedded by the event publisher.
    trigger_payload = context.get("trigger_payload") or {}
    lead = trigger_payload.get("lead") if isinstance(trigger_payload, dict) else None
    assignee_id = lead.get("assigned_to_id") if isinstance(lead, dict) else None
    user_uuid = _coerce_uuid(assignee_id)

    # 2) lead_id fallback → DB lookup.
    if user_uuid is None:
        lead_id_raw = None
        if isinstance(trigger_payload, dict):
            lead_id_raw = trigger_payload.get("lead_id")
            if lead_id_raw is None and isinstance(lead, dict):
                lead_id_raw = lead.get("id")
        lead_uuid = _coerce_uuid(lead_id_raw)
        if lead_uuid is not None:
            user_uuid = await _lookup_lead_owner(session, lead_uuid)

    # 3) contact fallback → most-recent lead for the run's contact.
    # Covers schedule-triggered runs bound to a contact_id.
    if user_uuid is None and run is not None and run.contact_id is not None:
        user_uuid = await _lookup_lead_owner_by_contact(session, run.contact_id)

    if user_uuid is None:
        return None
    if method == "email":
        return await _lookup_user_email(session, user_uuid)
    return await _lookup_user_phone(session, user_uuid)


async def _custom(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    """Walk a dot-path against the trigger payload, or return a
    literal email/phone.

    Reads the value from two places to accommodate both config
    shapes the UI writes:

      * dict-form ``config.recipient = {"kind": "custom", "path": "..."}``
      * string-form ``config.recipient = "custom"`` paired with a
        sibling ``config.recipient_custom = "..."`` — the send-editor
        component stores the free-text there.

    A value that contains ``@`` and no path separators is treated as
    a literal address; anything else is walked as a dot-path against
    ``trigger_payload``. Depth-capped so a pathological
    ``"a.b.c.d.e.f.g..."`` config can't bog the worker down."""
    params = _recipient_params(node)
    raw_value = params.get("path")
    if not isinstance(raw_value, str) or not raw_value:
        cfg = node.get("config") or {}
        raw_value = cfg.get("recipient_custom")
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    value = raw_value.strip()

    # Literal email — no dot walk. Bare emails contain "@" and don't
    # look like dotted paths ("first.last@example.com" is treated as
    # a literal because it contains @, even though it has dots).
    if "@" in value:
        return _trim(value)

    segments = value.split(".")
    if len(segments) > _MAX_PATH_DEPTH:
        logger.warning(
            "recipients._custom path too deep depth=%d cap=%d",
            len(segments),
            _MAX_PATH_DEPTH,
        )
        return None
    if any(len(s) > _MAX_SEGMENT_LEN for s in segments):
        return None

    payload = context.get("trigger_payload") or {}
    cursor: Any = payload
    for segment in segments:
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        cursor = cursor[segment]
    if isinstance(cursor, str) and cursor.strip():
        return _trim(cursor)
    return None


# --- DB-backed fallback lookups -----------------------------------------


async def _lookup_contact_field(
    session: AsyncSession,
    contact_id: uuid.UUID,
    field: str,
) -> str | None:
    from src.app.core.contacts.models import Contact

    column = getattr(Contact, field, None)
    if column is None:
        return None
    result = await session.execute(select(column).where(Contact.id == contact_id))
    value = result.scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return _trim(value)
    return None


async def _lookup_user_email(session: AsyncSession, user_uuid: uuid.UUID) -> str | None:
    """Email lives on ``tbl_user_info`` (joined via
    ``UserInfo.member_id == User.id``); ``User.email`` on the login
    model is a Python ``@property``, not a mapped column, so
    ``select(User.email)`` would raise ``ArgumentError`` at build
    time. Query the info table directly."""
    from src.app.core.users.models import User, UserInfo

    result = await session.execute(
        select(UserInfo.email)
        .join(User, User.id == UserInfo.member_id)
        .where(User.legacy_uuid == user_uuid)
    )
    value = result.scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return _trim(value)
    return None


async def _lookup_user_phone(session: AsyncSession, user_uuid: uuid.UUID) -> str | None:
    """Phone (``mobile_no``) lives on ``tbl_user_info`` alongside
    email — same join shape as :func:`_lookup_user_email`."""
    from src.app.core.users.models import User, UserInfo

    result = await session.execute(
        select(UserInfo.mobile_no)
        .join(User, User.id == UserInfo.member_id)
        .where(User.legacy_uuid == user_uuid)
    )
    value = result.scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return _trim(value)
    return None


async def _lookup_lead_owner(session: AsyncSession, lead_id: uuid.UUID) -> uuid.UUID | None:
    from src.app.core.leads.models import Lead

    result = await session.execute(select(Lead.assigned_to_id).where(Lead.id == lead_id))
    value = result.scalar_one_or_none()
    return value if isinstance(value, uuid.UUID) else None


async def _lookup_lead_owner_by_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> uuid.UUID | None:
    """Fallback owner lookup used when the run has no lead in its
    trigger_payload (schedule-triggered runs) but is bound to a
    contact. Returns the ``assigned_to_id`` of the contact's most
    recent lead that actually has an assignee — a contact with 3
    leads (2 unassigned, 1 assigned) still resolves to the
    assigned one rather than returning None."""
    from src.app.core.leads.models import Lead

    result = await session.execute(
        select(Lead.assigned_to_id)
        .where(Lead.contact_id == contact_id)
        .where(Lead.assigned_to_id.is_not(None))
        .order_by(Lead.id.desc())
        .limit(1)
    )
    value = result.scalar_one_or_none()
    return value if isinstance(value, uuid.UUID) else None


# --- Helpers -------------------------------------------------------------


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _trim(value: str) -> str:
    """Normalise + cap to defend against pathological inputs."""
    trimmed = value.strip()
    if len(trimmed) > _MAX_RESOLVED_LEN:
        return trimmed[:_MAX_RESOLVED_LEN]
    return trimmed


# Register built-ins on import. Idempotent.
register_resolver("contact.email", _contact_email)
register_resolver("contact.phone", _contact_phone)
register_resolver("user.email", _user_email)
register_resolver("lead.owner", _lead_owner)
register_resolver("custom", _custom)


__all__ = [
    "Resolver",
    "UnknownResolver",
    "is_registered",
    "list_registered",
    "register_resolver",
    "resolve",
]
