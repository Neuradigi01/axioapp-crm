"""Service layer for embeddable-widget API keys.

Three operations:

  - `issue(org_id, actor, name)` — generates `pk_live_<32-base62>`,
    stores only the bcrypt hash + 11-char prefix, returns the
    plaintext **once** so the Owner can copy-paste it into the
    install snippet. Emits `embed.key.issued` audit event.
  - `revoke(org_id, actor, key_id)` — soft-revokes by setting
    `revoked_at`. Idempotent (re-revoke is a no-op). Emits
    `embed.key.revoked` audit event.
  - `find_by_plain_key(plain, ip)` — the submission endpoint's
    lookup. Pulls candidates from the partial-prefix index (only
    live keys), bcrypt-verifies; on match, fire-and-forget updates
    `last_used_at` + `last_used_ip` (SHA-256-prefix-hashed for
    privacy). Returns None on miss.

The plaintext key format is `pk_live_` + 32 chars from
[A-Za-z0-9] (~190 bits of entropy in the suffix). The 11-char prefix
covers ~56B possible values — high enough that prefix collisions
between live keys are vanishingly rare, so the per-prefix scan
typically returns exactly one candidate.

bcrypt verification is intentionally slow (~50-100ms). On the
submission hot path this is acceptable for v1 since the per-IP +
per-key rate limits in Step 2 cap abuse. If submission latency
grows past comfort, cache `prefix → row` in Redis with a short TTL.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.embed import data_access as _da
from src.app.core.embed.models import EmbedKey
from src.app.shared.db import async_session

# Resource-type discriminator values for tbl_embed_keys.resource_type.
# CHECK constraint at DB-level (migration 0201) enforces membership.
RESOURCE_TYPE_LEAD_FORM = "lead_form"
RESOURCE_TYPE_AI_ASSISTANT = "ai_assistant"
_ALLOWED_RESOURCE_TYPES = frozenset(
    {RESOURCE_TYPE_LEAD_FORM, RESOURCE_TYPE_AI_ASSISTANT}
)

# Grace-period cap: rotate?grace_days=7 is the outer bound so an
# operator can't accidentally leave a rotated-but-still-live key
# floating around indefinitely.
_MAX_GRACE_DAYS = 7

logger = logging.getLogger(__name__)


_KEY_PREFIX = "pk_live_"
_KEY_SUFFIX_LEN = 32  # 32 chars × log2(62) ≈ 190 bits of entropy
_PREFIX_DISPLAY_LEN = 11  # len("pk_live_") + 3 = 11 chars persisted
_ALPHABET = string.ascii_letters + string.digits


def _generate_plain_key() -> str:
    """Return a new `pk_live_<32-base62>` plaintext key."""
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(_KEY_SUFFIX_LEN))
    return f"{_KEY_PREFIX}{suffix}"


def _hash_ip(ip: str | None) -> str | None:
    """Return SHA-256(ip)[:16] for privacy-respecting tracking.

    The full IP is never persisted. The 16-char prefix is enough for
    the Step 9 abuse-investigation surface to group submissions by
    IP without storing PII the user can be re-identified by.
    """
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _hash_key(plain: str) -> str:
    """bcrypt-hash a plaintext key. ~50-100ms by design."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_key(plain: str, stored_hash: str) -> bool:
    """Constant-time bcrypt verify. Returns False on any error so a
    malformed stored hash never crashes the submission path."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def issue(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str | None = None,
    resource_type: str = RESOURCE_TYPE_LEAD_FORM,
    resource_id: uuid.UUID | None = None,
    allowed_origins: list[str] | None = None,
    rate_limit_per_hour: int | None = None,
) -> tuple[EmbedKey, str]:
    """Generate + persist a new key. Returns (row, plaintext).

    ``resource_type`` / ``resource_id`` bind the key to a specific
    resource — ``ai_assistant`` keys carry the assistant id so the
    public router can resolve the target assistant from just the
    bearer token. ``allowed_origins`` is an advisory ``Origin``-
    header allow-list; ``rate_limit_per_hour`` overrides the per-key
    default (300).

    Multi-form binding (Step 3): for ``lead_form`` keys, ``resource_id``
    is the id of a ``tbl_widget_configs`` row and MUST point at a live
    form the caller's org owns. When omitted, we resolve the org's
    default form so legacy callers that don't pass ``form_id`` still
    produce a valid key (rejected with 422 if the org has no default —
    only possible when the org has never opened Settings → Widget)."""
    if resource_type not in _ALLOWED_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "invalid_resource_type", "value": resource_type},
        )
    if resource_type == RESOURCE_TYPE_AI_ASSISTANT and resource_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "resource_id_required_for_ai_assistant"},
        )
    if resource_type == RESOURCE_TYPE_LEAD_FORM:
        resource_id = await _resolve_lead_form_binding(
            session, org_id=org_id, form_id=resource_id
        )

    plain = _generate_plain_key()
    prefix = plain[:_PREFIX_DISPLAY_LEN]
    hashed = _hash_key(plain)

    row = EmbedKey(
        org_id=org_id,
        name=(name or None),
        prefix=prefix,
        hash=hashed,
        created_by=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        allowed_origins=list(allowed_origins or []),
        rate_limit_per_hour=(rate_limit_per_hour if rate_limit_per_hour is not None else 300),
    )
    _da.insert_embed_key(session, row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "embed.key.issued",
        entity_type="embed_key",
        entity_id=row.id,
        after={
            "key_id": str(row.id),
            "name": row.name,
            "prefix": row.prefix,
            "resource_type": row.resource_type,
            "resource_id": str(row.resource_id) if row.resource_id else None,
        },
    )
    return row, plain


async def revoke(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    key_id: uuid.UUID,
) -> EmbedKey:
    """Soft-revoke. Idempotent — re-revoking is a no-op."""
    row = await _da.get_embed_key_by_id(session, key_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="embed key not found")
    if row.revoked_at is not None:
        return row  # already revoked — no-op

    row.revoked_at = datetime.now(UTC)
    row.revoked_by = actor_id
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "embed.key.revoked",
        entity_type="embed_key",
        entity_id=row.id,
        after={"key_id": str(row.id), "prefix": row.prefix},
    )
    return row


async def list_keys(
    session: AsyncSession,
    *,
    form_id: uuid.UUID | None = None,
) -> list[EmbedKey]:
    """List all keys (live + revoked) for the active org.

    When ``form_id`` is supplied, only keys pinned to that form are
    returned. Powers the per-form key panel on the Settings → Forms
    edit page.
    """
    if form_id is not None:
        return await _da.list_embed_keys_for_resource(
            session,
            resource_type=RESOURCE_TYPE_LEAD_FORM,
            resource_id=form_id,
        )
    return await _da.list_embed_keys(session)


async def _resolve_lead_form_binding(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    form_id: uuid.UUID | None,
) -> uuid.UUID:
    """Resolve the ``form_id`` an issued lead_form key should point at.

    * Explicit ``form_id`` — validated: must belong to caller's org
      AND not be soft-deleted. 404 / 422 otherwise.
    * ``None`` — fall back to the org's default form. 422 when the
      org has no default (never opened Settings → Widget).

    Returns the resolved form id; never None. Callers use the return
    value as ``EmbedKey.resource_id``.
    """
    if form_id is not None:
        form = await _da.get_widget_form_by_id(session, form_id)
        if form is None or form.org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"reason": "form_not_found"},
            )
        if form.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "form_deleted"},
            )
        return form.id

    default_form = await _da.get_widget_config_for_org(session, org_id)
    if default_form is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "no_default_form",
                "message": (
                    "Open Settings → Forms to create a form first, then "
                    "issue an embed key for it."
                ),
            },
        )
    return default_form.id


async def find_by_plain_key(plain: str, *, ip: str | None = None) -> EmbedKey | None:
    """Submission-path lookup. Returns the matching live key row or
    None. Best-effort updates `last_used_at` / `last_used_ip` after
    a successful match (does not block the caller on failure).

    Bypasses the tenant ORM filter because the submission endpoint
    is unauthenticated — the caller has no org context yet. The
    key's `org_id` BECOMES the request's org context downstream.
    """
    if not plain or not plain.startswith(_KEY_PREFIX):
        return None
    prefix = plain[:_PREFIX_DISPLAY_LEN]
    if len(prefix) != _PREFIX_DISPLAY_LEN:
        return None

    async with async_session() as session:
        rows = await _da.list_embed_keys_by_prefix_unrevoked(session, prefix)
        match: EmbedKey | None = None
        for candidate in rows:
            if _verify_key(plain, candidate.hash):
                match = candidate
                break

        if match is None:
            return None

        matched_id = match.id
        try:
            await _da.update_embed_key_last_used(
                session,
                key_id=matched_id,
                when=datetime.now(UTC),
                ip_hash=_hash_ip(ip),
            )
            await session.commit()
        except Exception:
            logger.exception("embed.last_used_update failed for key %s", matched_id)

        return match


# --- AI-assistant public path (Step 14) ---------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedEmbedKey:
    """The subset of :class:`EmbedKey` the public router needs. Kept
    as a plain dataclass so we don't ferry a live ORM instance across
    the request lifecycle (the session that loaded it closes before
    the router handler runs)."""

    key_id: uuid.UUID
    org_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID | None
    allowed_origins: tuple[str, ...]
    rate_limit_per_hour: int
    prefix: str


async def resolve_embed_key(plain: str, *, ip: str | None = None) -> ResolvedEmbedKey | None:
    """Grace-aware lookup for the AI-assistants public router.

    Accepts keys that are:
      * live (``revoked_at IS NULL``), OR
      * within a rotate-with-grace window (``revoked_at`` set but
        ``grace_expires_at > now()``).

    Returns ``None`` on no-match. Callers translate ``None`` to a
    401 with an identical body so an attacker can't distinguish
    "wrong key" from "revoked past grace".
    """
    if not plain or not plain.startswith(_KEY_PREFIX):
        return None
    prefix = plain[:_PREFIX_DISPLAY_LEN]
    if len(prefix) != _PREFIX_DISPLAY_LEN:
        return None

    now = datetime.now(UTC)
    async with async_session() as session:
        rows = await _da.list_embed_keys_by_prefix_live(
            session, prefix=prefix, now=now
        )
        match: EmbedKey | None = None
        for candidate in rows:
            if _verify_key(plain, candidate.hash):
                match = candidate
                break

        if match is None:
            return None

        matched_id = match.id
        # Snapshot the fields we need BEFORE the session closes.
        snapshot = ResolvedEmbedKey(
            key_id=match.id,
            org_id=match.org_id,
            resource_type=match.resource_type,
            resource_id=match.resource_id,
            allowed_origins=tuple(match.allowed_origins or ()),
            rate_limit_per_hour=int(match.rate_limit_per_hour or 300),
            prefix=match.prefix,
        )

        try:
            await _da.update_embed_key_last_used(
                session,
                key_id=matched_id,
                when=now,
                ip_hash=_hash_ip(ip),
            )
            await session.commit()
        except Exception:
            logger.exception("embed.last_used_update failed for key %s", matched_id)

        return snapshot


def assert_ai_assistant_key(resolved: ResolvedEmbedKey | None) -> ResolvedEmbedKey:
    """Guard for the AI-assistants public router. Raises 401 with a
    stable ``invalid_key`` reason if the resolved key isn't scoped
    to an AI assistant (wrong resource_type, or resource_id nulled
    out by a bad admin edit). Same error body as an unknown key —
    no side channel."""
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason": "invalid_key"},
        )
    if (
        resolved.resource_type != RESOURCE_TYPE_AI_ASSISTANT
        or resolved.resource_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason": "invalid_key"},
        )
    return resolved


async def rotate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    key_id: uuid.UUID,
    grace_days: int = 0,
) -> tuple[EmbedKey, str]:
    """Issue a fresh key with the same ``(resource_type, resource_id,
    allowed_origins, rate_limit_per_hour, name)`` as the target + set
    the old key's ``revoked_at`` (with optional grace window). Returns
    the NEW row + plaintext.

    ``grace_days`` in ``[0, 7]``:
      * ``0`` → immediate revoke (default).
      * ``>0`` → old key stays live for that many days so the operator
        can swap the new key into their site without downtime.
    """
    if grace_days < 0 or grace_days > _MAX_GRACE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "reason": "grace_days_out_of_range",
                "min": 0,
                "max": _MAX_GRACE_DAYS,
            },
        )

    old = await _da.get_embed_key_by_id(session, key_id)
    if old is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="embed key not found"
        )
    if old.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "already_revoked"},
        )

    new_row, plain = await issue(
        session,
        org_id=org_id,
        actor_id=actor_id,
        name=old.name,
        resource_type=old.resource_type,
        resource_id=old.resource_id,
        allowed_origins=list(old.allowed_origins or []),
        rate_limit_per_hour=old.rate_limit_per_hour,
    )

    now = datetime.now(UTC)
    grace_expires_at = now + timedelta(days=grace_days) if grace_days > 0 else None
    await _da.set_grace_expiry(
        session,
        key_id=key_id,
        revoked_at=now,
        revoked_by=actor_id,
        grace_expires_at=grace_expires_at,
    )
    await session.commit()

    await audit.log(
        "embed.key.rotated",
        entity_type="embed_key",
        entity_id=old.id,
        after={
            "old_key_id": str(old.id),
            "new_key_id": str(new_row.id),
            "grace_days": grace_days,
        },
    )
    return new_row, plain


async def revoke_now(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,  # noqa: ARG001 — tenant filter enforces scope on the DAL read
    actor_id: uuid.UUID,
    key_id: uuid.UUID,
) -> EmbedKey:
    """Hard revoke: ``revoked_at=now()`` + ``grace_expires_at=NULL``
    so the sweeper doesn't try to re-close a key that never had a
    grace window. Idempotent — a re-revoke updates the timestamp
    without emitting a second audit event.

    In-flight SSE streams for this key are closed by the public
    router (which reads :mod:`~core.ai_assistants.sse_registry`) —
    kept out of this service so the DAL layer doesn't grow a
    dependency on the AI-assistants module."""
    row = await _da.get_embed_key_by_id(session, key_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="embed key not found"
        )
    already_revoked = row.revoked_at is not None
    now = datetime.now(UTC)
    await _da.set_grace_expiry(
        session,
        key_id=key_id,
        revoked_at=now,
        revoked_by=actor_id,
        grace_expires_at=None,
    )
    await session.commit()
    await session.refresh(row)
    if not already_revoked:
        await audit.log(
            "embed.key.revoked_now",
            entity_type="embed_key",
            entity_id=row.id,
            after={"key_id": str(row.id), "prefix": row.prefix},
        )
    return row


async def list_keys_for_resource(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
) -> list[EmbedKey]:
    """List keys bound to one resource. Used by the operator UI's
    per-assistant embed panel."""
    return await _da.list_embed_keys_for_resource(
        session, resource_type=resource_type, resource_id=resource_id
    )


__all__ = [
    "RESOURCE_TYPE_AI_ASSISTANT",
    "RESOURCE_TYPE_LEAD_FORM",
    "ResolvedEmbedKey",
    "assert_ai_assistant_key",
    "find_by_plain_key",
    "issue",
    "list_keys",
    "list_keys_for_resource",
    "resolve_embed_key",
    "revoke",
    "revoke_now",
    "rotate",
]
