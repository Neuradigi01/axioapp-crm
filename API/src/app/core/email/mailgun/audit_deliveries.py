"""Audit-trail persistence for every Mailgun inbound webhook receipt.

Track 6 Step 1. Best-effort — an audit-write failure logs a warning +
returns; the caller's response never blocks on this. Delivery outcome
enums are locked here so callers never spell them wrong.

Table shape: see ``tbl_email_inbound_deliveries`` in migration
``0237_email_inbound_audit``. **System-level** — no ``org_id`` column
because many outcomes (signature_rejected / replay_rejected /
timestamp_rejected / size_rejected_before_download) fire BEFORE we
know which tenant the delivery would belong to.

Retention: 90 days by default, tunable via
``EMAIL_INBOUND_DELIVERIES_RETAIN_DAYS``. Beat entry in
``celery_config.py`` runs the retention sweep once a day.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base, async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums (module-level constants → caller can't spell wrong)
# ---------------------------------------------------------------------------


OUTCOME_ENQUEUED = "enqueued"
OUTCOME_SIGNATURE_REJECTED = "signature_rejected"
OUTCOME_REPLAY_REJECTED = "replay_rejected"
OUTCOME_TIMESTAMP_REJECTED = "timestamp_rejected"
OUTCOME_SIZE_REJECTED = "size_rejected_before_download"

OUTCOMES = (
    OUTCOME_ENQUEUED,
    OUTCOME_SIGNATURE_REJECTED,
    OUTCOME_REPLAY_REJECTED,
    OUTCOME_TIMESTAMP_REJECTED,
    OUTCOME_SIZE_REJECTED,
)

SIG_VALID = "valid"
SIG_INVALID = "invalid"
SIG_MISSING = "missing"

REPLAY_FRESH = "fresh"
REPLAY_REPLAY = "replayed"

TIMESTAMP_FRESH = "fresh"
TIMESTAMP_STALE = "stale"


# ---------------------------------------------------------------------------
# ORM class (declared here so ``core.email.mailgun.audit_deliveries``
# is the single source of truth for the audit table shape).
# ---------------------------------------------------------------------------


class EmailInboundDelivery(Base):
    """One row per webhook receipt. NO ``org_id`` — deliberate deviation
    from CLAUDE.md rule 2, documented in the migration + this class."""

    __tablename__ = "tbl_email_inbound_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    mailgun_delivery_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    mailgun_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False)
    replay_status: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp_status: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_size_bytes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    attachment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    client_ip: Mapped[str | None] = mapped_column(INET(), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('enqueued', 'signature_rejected', 'replay_rejected', "
            "'timestamp_rejected', 'size_rejected_before_download')",
            name="ck_email_inbound_deliveries_outcome",
        ),
    )


# ---------------------------------------------------------------------------
# Write helper — best-effort, never raises to caller
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditPayload:
    """Structured payload for :func:`write_audit`. Freezing this
    avoids typoed kwargs at every call site."""

    outcome: str
    signature_status: str
    replay_status: str
    timestamp_status: str
    mailgun_delivery_id: str | None = None
    mailgun_message_id: str | None = None
    recipient: str | None = None
    sender: str | None = None
    payload_size_bytes: int | None = None
    attachment_count: int | None = None
    outcome_detail: dict[str, Any] | None = None
    client_ip: str | None = None
    user_agent: str | None = None


async def write_audit(payload: AuditPayload) -> None:
    """Persist one audit row. Best-effort — swallows every exception.

    Opens its own session (not the caller's) so a rollback in the
    webhook path never rolls this row back.

    The caller is expected to schedule this via
    ``asyncio.create_task(write_audit(...))`` so response time stays
    constant regardless of DB latency. If the caller awaits directly,
    a slow write still doesn't leak information (the response body
    doesn't reveal the audit's presence) — but the constant-time
    guarantee is only kept by the fire-and-forget pattern.
    """
    try:
        # Sanitise the IP before we hand it to Postgres INET — an
        # invalid string in the header would otherwise blow up the
        # entire audit-write. Bad IP = drop the field.
        ip_str: str | None = None
        if payload.client_ip:
            try:
                ipaddress.ip_address(payload.client_ip)
                ip_str = payload.client_ip
            except (ValueError, TypeError):
                pass

        async with async_session() as session:
            row = EmailInboundDelivery(
                mailgun_delivery_id=payload.mailgun_delivery_id,
                mailgun_message_id=payload.mailgun_message_id,
                signature_status=payload.signature_status,
                replay_status=payload.replay_status,
                timestamp_status=payload.timestamp_status,
                recipient=payload.recipient,
                sender=payload.sender,
                payload_size_bytes=payload.payload_size_bytes,
                attachment_count=payload.attachment_count,
                outcome=payload.outcome,
                outcome_detail=payload.outcome_detail or {},
                client_ip=ip_str,
                user_agent=(payload.user_agent or None),
            )
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "email_inbound_audit.write_audit failed: outcome=%s exc=%s",
            payload.outcome,
            exc,
        )


# ---------------------------------------------------------------------------
# Retention sweep — called from Celery beat (Step 1 wires
# ``sweep_inbound_deliveries_daily`` under ``mailgun/tasks.py``).
# ---------------------------------------------------------------------------


import os  # noqa: E402


_DEFAULT_RETAIN_DAYS = 90
_BATCH_SIZE = 10_000


def _retain_days() -> int:
    try:
        return max(1, int(os.getenv("EMAIL_INBOUND_DELIVERIES_RETAIN_DAYS", str(_DEFAULT_RETAIN_DAYS))))
    except ValueError:
        return _DEFAULT_RETAIN_DAYS


async def sweep_expired(session) -> dict[str, Any]:
    """Delete rows older than the retention window. Batched at
    :data:`_BATCH_SIZE` rows per beat run so a large backlog after a
    retention-days shrink can't stall the loop.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_retain_days())
    total_deleted = 0
    while True:
        result = await session.execute(
            sql_text(
                """
                DELETE FROM tbl_email_inbound_deliveries
                 WHERE id IN (
                    SELECT id FROM tbl_email_inbound_deliveries
                     WHERE received_at < :cutoff
                     LIMIT :batch
                 )
                """
            ),
            {"cutoff": cutoff, "batch": _BATCH_SIZE},
        )
        deleted = result.rowcount or 0
        total_deleted += deleted
        if deleted < _BATCH_SIZE:
            break
    if total_deleted:
        await session.commit()
        logger.info(
            "email_inbound_audit.sweep_expired deleted=%d cutoff=%s",
            total_deleted,
            cutoff.isoformat(),
        )
    return {
        "deleted": total_deleted,
        "cutoff": cutoff.isoformat(),
        "at": now.isoformat(),
    }


__all__ = [
    "OUTCOMES",
    "OUTCOME_ENQUEUED",
    "OUTCOME_REPLAY_REJECTED",
    "OUTCOME_SIGNATURE_REJECTED",
    "OUTCOME_SIZE_REJECTED",
    "OUTCOME_TIMESTAMP_REJECTED",
    "REPLAY_FRESH",
    "REPLAY_REPLAY",
    "SIG_INVALID",
    "SIG_MISSING",
    "SIG_VALID",
    "TIMESTAMP_FRESH",
    "TIMESTAMP_STALE",
    "AuditPayload",
    "EmailInboundDelivery",
    "sweep_expired",
    "write_audit",
]
