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
from datetime import UTC, datetime

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.embed import data_access as _da
from src.app.core.embed.models import EmbedKey
from src.app.shared.db import async_session

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
) -> tuple[EmbedKey, str]:
    """Generate + persist a new key. Returns (row, plaintext)."""
    plain = _generate_plain_key()
    prefix = plain[:_PREFIX_DISPLAY_LEN]
    hashed = _hash_key(plain)

    row = EmbedKey(
        org_id=org_id,
        name=(name or None),
        prefix=prefix,
        hash=hashed,
        created_by=actor_id,
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
) -> list[EmbedKey]:
    """List all keys (live + revoked) for the active org."""
    return await _da.list_embed_keys(session)


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


__all__ = ["find_by_plain_key", "issue", "list_keys", "revoke"]
