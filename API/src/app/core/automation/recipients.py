"""Recipient resolver registry for the automation dispatcher.

A trigger row carries ``recipient_resolver`` (text) +
``recipient_resolver_config`` (JSONB). At dispatch time the engine
asks this module for the concrete send address (email / phone /
device token) given the published event payload.

Four built-in resolvers, each keyed by string:

* ``contact.email``  — reads ``payload['contact']['email']``; falls
                       back to a DB lookup by ``payload['contact_id']``
                       when the publisher didn't denormalise the
                       contact dict into the envelope.
* ``contact.phone``  — same shape, returns the E.164 phone.
* ``user.email``     — reads ``payload['user']['email']`` (used by
                       ``user.signed_up`` and any system event whose
                       recipient is the user that fired the event).
* ``custom``         — reads ``recipient_resolver_config['path']`` and
                       walks it as a dot-path into the payload. The
                       operator types the JSONPath in the trigger
                       editor (Step 8).

Returns ``None`` when the path can't resolve — the dispatcher logs
a ``skipped`` run row with ``error='no_recipient'`` so the operator
sees the failure in the run-history UI.

The registry is the same shape as
:mod:`core.conversations.registry` — module-level dict, lookup by
string, raise :class:`UnknownResolver` when the key is unknown so a
typo in the trigger config doesn't silently send nowhere.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class UnknownResolver(Exception):
    """Raised when ``recipient_resolver`` is not in the registry."""

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown recipient resolver {name!r}")
        self.name = name


# Resolver signature — coroutine returning the address string or None.
Resolver = Callable[
    [AsyncSession, dict[str, Any], dict[str, Any]],
    Awaitable[Optional[str]],
]


_resolvers: dict[str, Resolver] = {}


def register_resolver(name: str, resolver: Resolver) -> None:
    """Register ``resolver`` under ``name``. Idempotent on
    ``(name, resolver)`` — re-registering the same pair is a no-op
    so module-import side effects don't double-add."""
    existing = _resolvers.get(name)
    if existing is resolver:
        return
    _resolvers[name] = resolver


async def resolve(
    name: str,
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> Optional[str]:
    """Look up + invoke the resolver. Unknown names raise
    :class:`UnknownResolver`."""
    fn = _resolvers.get(name)
    if fn is None:
        raise UnknownResolver(name)
    return await fn(session, payload, config or {})


# --- built-in resolvers ----------------------------------------------


async def _contact_email(
    session: AsyncSession,
    payload: dict[str, Any],
    _config: dict[str, Any],
) -> Optional[str]:
    contact = payload.get("contact")
    if isinstance(contact, dict):
        email = contact.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip()
    contact_id = payload.get("contact_id")
    if isinstance(contact_id, str):
        try:
            contact_uuid = uuid.UUID(contact_id)
        except ValueError:
            return None
        return await _lookup_contact_field(session, contact_uuid, "email")
    if isinstance(contact_id, uuid.UUID):
        return await _lookup_contact_field(session, contact_id, "email")
    return None


async def _contact_phone(
    session: AsyncSession,
    payload: dict[str, Any],
    _config: dict[str, Any],
) -> Optional[str]:
    contact = payload.get("contact")
    if isinstance(contact, dict):
        phone = contact.get("phone")
        if isinstance(phone, str) and phone.strip():
            return phone.strip()
    contact_id = payload.get("contact_id")
    if isinstance(contact_id, str):
        try:
            contact_uuid = uuid.UUID(contact_id)
        except ValueError:
            return None
        return await _lookup_contact_field(session, contact_uuid, "phone")
    if isinstance(contact_id, uuid.UUID):
        return await _lookup_contact_field(session, contact_id, "phone")
    return None


async def _user_email(
    session: AsyncSession,
    payload: dict[str, Any],
    _config: dict[str, Any],
) -> Optional[str]:
    user = payload.get("user")
    if isinstance(user, dict):
        email = user.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip()
    user_id = payload.get("user_id")
    if isinstance(user_id, str):
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return None
        return await _lookup_user_email(session, user_uuid)
    if isinstance(user_id, uuid.UUID):
        return await _lookup_user_email(session, user_id)
    return None


async def _custom(
    _session: AsyncSession,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> Optional[str]:
    path = config.get("path")
    if not isinstance(path, str) or not path:
        return None
    cursor: Any = payload
    for segment in path.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        cursor = cursor[segment]
    if isinstance(cursor, str) and cursor.strip():
        return cursor.strip()
    return None


# --- DB-backed fallback lookups --------------------------------------


async def _lookup_contact_field(
    session: AsyncSession, contact_id: uuid.UUID, field: str
) -> Optional[str]:
    from src.app.core.contacts.models import Contact

    column = getattr(Contact, field, None)
    if column is None:
        return None
    row = (
        await session.execute(
            select(column).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    if isinstance(row, str) and row.strip():
        return row.strip()
    return None


async def _lookup_user_email(
    session: AsyncSession, user_uuid: uuid.UUID
) -> Optional[str]:
    from src.app.core.users.models import User

    row = (
        await session.execute(
            select(User.email).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one_or_none()
    if isinstance(row, str) and row.strip():
        return row.strip()
    return None


# --- registration -----------------------------------------------------


register_resolver("contact.email", _contact_email)
register_resolver("contact.phone", _contact_phone)
register_resolver("user.email", _user_email)
register_resolver("custom", _custom)


__all__ = [
    "Resolver",
    "UnknownResolver",
    "register_resolver",
    "resolve",
]
