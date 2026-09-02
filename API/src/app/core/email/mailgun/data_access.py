"""Pure CRUD helpers for the Mailgun inbound module.

Two responsibilities:

  * Redis replay-cache guard (``check_and_record_replay``) —
    prevents an attacker from re-posting a captured
    ``(timestamp, token, signature)`` triplet within the 10-minute
    window. Fails **closed** on Redis outage per the locked design
    (a replay is worse than a dropped legit reply — replays are
    attacker traffic; on Redis outage Mailgun retries after we 5xx,
    and Redis coming back finishes delivery).
  * DLQ writes (``insert_dlq_row``) for Celery tasks that exhaust
    their retry budget.

DAL discipline (memory ``feedback_backend_layered_architecture.md``):
no ``session.commit / flush / refresh / rollback`` here — those live
in ``service.py``. Redis client is not a transactional store; direct
``SET NX PX`` is fine at this layer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.mailgun.dlq_models import EmailInboundDlq
from src.app.shared.rate_limit_shared import _redis  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

# All Mailgun-webhook Redis keys share this prefix so ops can grep +
# expire the whole namespace under load.
_REPLAY_PREFIX = "mgw:seen:"
_REPLAY_TTL_SECONDS = 600  # 10 minutes


async def check_and_record_replay(token: str) -> bool:
    """Atomic "first-seen wins" check for the Mailgun-delivery token.

    Returns:
        True — token is fresh; the caller may proceed to enqueue.
        False — either a genuine replay OR Redis is down (fail-CLOSED
        by design; a replay is worse than the transient reject that
        Mailgun retries anyway).
    """
    if not token:
        return False
    client = _redis()
    if client is None:
        logger.error(
            "mailgun.replay check: redis client unavailable — failing closed"
        )
        return False
    try:
        # SET NX PX = atomic "set if not exists with TTL in ms".
        # Returns None if the key already existed, "OK" if we set it.
        result = await client.set(
            f"{_REPLAY_PREFIX}{token}",
            "1",
            nx=True,
            px=_REPLAY_TTL_SECONDS * 1000,
        )
        return bool(result)
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("mailgun.replay redis error: %s — failing closed", exc)
        return False


def insert_dlq_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    mailgun_delivery_id: str | None,
    pending_inbound_path: str,
    error_reason: str,
    error_details: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> EmailInboundDlq:
    """Stage a DLQ INSERT. Caller commits."""
    row = EmailInboundDlq(
        org_id=org_id,
        mailgun_delivery_id=mailgun_delivery_id,
        pending_inbound_path=pending_inbound_path,
        error_reason=error_reason,
        error_details=error_details,
        retry_count=retry_count,
    )
    session.add(row)
    return row


async def list_dlq_rows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EmailInboundDlq]:
    """List DLQ rows, newest first. Pass ``org_id=None`` for the
    system-level view (unknown-recipient etc.); pass an org_id for the
    per-tenant view. Used by the Step 5 admin endpoint."""
    stmt = select(EmailInboundDlq).order_by(EmailInboundDlq.created_at.desc())
    if org_id is not None:
        stmt = stmt.where(EmailInboundDlq.org_id == org_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_dlq_row(
    session: AsyncSession, *, dlq_id: uuid.UUID
) -> EmailInboundDlq | None:
    """Point read used by the reprocess endpoint (Step 5)."""
    result = await session.execute(
        select(EmailInboundDlq).where(EmailInboundDlq.id == dlq_id)
    )
    return result.scalar_one_or_none()


__all__ = [
    "check_and_record_replay",
    "get_dlq_row",
    "insert_dlq_row",
    "list_dlq_rows",
]
