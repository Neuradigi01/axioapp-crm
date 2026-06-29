"""Recipient resolver registry for workflow Send actions.

A Send node carries ``config.recipient`` which is either a plain
string identifying the resolver (``"contact.email"``) or a dict
``{"kind": "custom", ...config}`` for resolvers that need their
own config.

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
from typing import Any, Awaitable, Callable, Optional

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
Resolver = Callable[..., Awaitable[Optional[str]]]


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
) -> Optional[str]:
    """Look up + invoke a resolver. Raises :class:`UnknownResolver`
    for unregistered names — the Send handler catches + maps to a
    skipped step."""
    fn = _resolvers.get(name)
    if fn is None:
        raise UnknownResolver(name)
    return await fn(session, run=run, node=node, context=context)


# --- Built-in resolvers --------------------------------------------------


async def _contact_email(
    session: AsyncSession,
    *,
    run,
    node: dict[str, Any],
    context: dict[str, Any],
) -> Optional[str]:
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
) -> Optional[str]:
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
) -> Optional[str]:
    """Look up the email of a user. The node config can supply an
    explicit ``user_id`` (for "notify deal owner" patterns);
    otherwise we fall back to the workflow's creator."""
    cfg = (node.get("config") or {}).get("recipient") or {}
    user_id_raw = cfg.get("user_id")
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
) -> Optional[str]:
    """Resolve the lead's assigned user, then that user's email or
    phone per ``config.method`` (defaults to ``email``)."""
    cfg = (node.get("config") or {}).get("recipient") or {}
    method = cfg.get("method", "email")
    if method not in ("email", "phone"):
        return None

    # The trigger payload typically carries either a `lead` dict
    # with the assignee snapshot, or a `lead_id` we can look up.
    trigger_payload = context.get("trigger_payload") or {}
    lead = trigger_payload.get("lead") or {}
    assignee_id = lead.get("assigned_to_id") if isinstance(lead, dict) else None
    if assignee_id is None:
        assignee_id = trigger_payload.get("lead", {}).get("assigned_to_id")
    user_uuid = _coerce_uuid(assignee_id)

    if user_uuid is None:
        # Fall back to a DB lookup off lead_id when the snapshot
        # didn't include the assignee.
        lead_id_raw = trigger_payload.get("lead_id") or trigger_payload.get(
            "lead", {}
        ).get("id")
        lead_uuid = _coerce_uuid(lead_id_raw)
        if lead_uuid is not None:
            user_uuid = await _lookup_lead_owner(session, lead_uuid)

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
) -> Optional[str]:
    """Walk a dot-path against the trigger payload. Depth-capped so
    a pathological ``"a.b.c.d.e.f.g..."`` config can't bog the
    worker down."""
    cfg = (node.get("config") or {}).get("recipient") or {}
    path = cfg.get("path")
    if not isinstance(path, str) or not path:
        return None
    segments = path.split(".")
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
) -> Optional[str]:
    from src.app.core.contacts.models import Contact

    column = getattr(Contact, field, None)
    if column is None:
        return None
    result = await session.execute(
        select(column).where(Contact.id == contact_id)
    )
    value = result.scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return _trim(value)
    return None


async def _lookup_user_email(
    session: AsyncSession, user_uuid: uuid.UUID
) -> Optional[str]:
    from src.app.core.users.models import User

    result = await session.execute(
        select(User.email).where(User.legacy_uuid == user_uuid)
    )
    value = result.scalar_one_or_none()
    if isinstance(value, str) and value.strip():
        return _trim(value)
    return None


async def _lookup_user_phone(
    session: AsyncSession, user_uuid: uuid.UUID
) -> Optional[str]:
    """Best-effort phone lookup. The User model in this codebase
    doesn't carry a phone today — returns None until that's added.
    Kept here so the resolver shape stays stable when phone-on-user
    lands."""
    return None


async def _lookup_lead_owner(
    session: AsyncSession, lead_id: uuid.UUID
) -> Optional[uuid.UUID]:
    from src.app.core.leads.models import Lead

    result = await session.execute(
        select(Lead.assigned_to_id).where(Lead.id == lead_id)
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
