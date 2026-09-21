"""Business logic for reputation event ingest.

One public entry point: :func:`handle_mailgun_event`. Given a
Mailgun event kind + attribution metadata (``org_id``, envelope,
domain), it:

  1. Loads (or upserts) the ``tbl_organization_email_reputation``
     row for the (org × envelope × domain) tuple.
  2. Bumps the Redis 24h counter via :func:`.counters.incr_counter`.
  3. Mirrors the increment into the row's ``*_count_24h`` column so
     the dashboard can render without a Redis read.
  4. Commits the session.

Layering: this is the ONLY layer that calls
``session.commit / flush / refresh``. The Celery task in
:mod:`.events_webhook` calls this once per event.

Event kind mapping (locked at Step 3):

  * ``delivered``          → ``delivered_count_24h``   ← Redis ``delivered``
  * ``failed`` permanent   → ``bounce_count_24h``      ← Redis ``bounced``
  * ``failed`` temporary   → NO-OP (Mailgun retries; transient blip)
  * ``complained``         → ``complaint_count_24h``   ← Redis ``complained``
  * ``unsubscribed``       → Redis ``unsubscribed`` only (no DB mirror
                              — dashboards don't render unsubs here;
                              consent module owns that surface)
  * ``rejected``           → NO-OP for reputation (pre-send Mailgun
                              refusal; the send-gate on Step 5
                              never saw the message land in ISP-space)
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation import counters, data_access
from src.app.core.email.reputation.models import OrganizationEmailReputation

logger = logging.getLogger(__name__)


# Mapping from Mailgun's event verb (or (event, severity) tuple for
# ``failed``) to (Redis counter key, DB mirror column-or-None). The
# tuple form avoids two branches: caller composes the key upstream.
_EVENT_MAP: dict[str, tuple[str, str | None]] = {
    "delivered": ("delivered", "delivered_count_24h"),
    "failed:permanent": ("bounced", "bounce_count_24h"),
    "complained": ("complained", "complaint_count_24h"),
    "unsubscribed": ("unsubscribed", None),
}


async def _get_or_create_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> OrganizationEmailReputation:
    """Atomic-friendly upsert. Reads first; INSERTs on miss; on
    ``IntegrityError`` (concurrent-write race caught by the partial
    unique index) rolls back the failed INSERT and re-reads.

    Never returns None — the caller drives commit semantics after
    the row is in the session cache.
    """
    row = await data_access.get_row(
        session, org_id=org_id, envelope_type=envelope_type, domain_id=domain_id
    )
    if row is not None:
        return row

    # Stage the INSERT. Flush inside a savepoint so an IntegrityError
    # from the concurrent-INSERT case doesn't taint the outer
    # transaction — we still want to commit the counter bump.
    async with session.begin_nested():
        try:
            row = data_access.insert_row(
                session,
                org_id=org_id,
                envelope_type=envelope_type,
                domain_id=domain_id,
            )
            await session.flush()
            return row
        except IntegrityError:
            pass  # savepoint rolled back; fall through to re-read.

    row = await data_access.get_row(
        session, org_id=org_id, envelope_type=envelope_type, domain_id=domain_id
    )
    if row is None:
        # Extremely unlikely — a concurrent DELETE between the
        # IntegrityError and the re-read. Insert once more without the
        # savepoint safety net; if this ALSO fails we let the caller
        # see the exception (Mailgun retries after our 5xx).
        row = data_access.insert_row(
            session,
            org_id=org_id,
            envelope_type=envelope_type,
            domain_id=domain_id,
        )
        await session.flush()
    return row


async def handle_mailgun_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
    event_kind: str,
    severity: str | None = None,
) -> None:
    """Ingest one Mailgun event's counter effect.

    ``event_kind`` is Mailgun's verbatim ``event`` field:
    ``delivered``, ``failed``, ``complained``, ``unsubscribed``,
    ``rejected``, ``accepted``, ``opened``, ``clicked``. Only the
    counter-relevant subset is mapped in :data:`_EVENT_MAP`; every
    other kind falls through as a silent no-op (logged at DEBUG).

    ``severity`` is only meaningful for ``event_kind='failed'``:

      * ``permanent`` → bounce (address doesn't exist / mailbox full
        beyond retry / policy reject)
      * ``temporary`` → soft bounce; Mailgun retries; NO counter bump.

    Missing severity on ``failed`` is treated as ``permanent`` — the
    safer default (attribute the failure) since a Mailgun-side
    payload change that dropped ``severity`` would otherwise silently
    stop counting bounces.
    """
    key: str
    if event_kind == "failed":
        sev = (severity or "permanent").lower().strip()
        if sev == "temporary":
            logger.debug("reputation.handle_mailgun_event: failed/temporary — no counter bump")
            return
        key = "failed:permanent"
    else:
        key = event_kind

    entry = _EVENT_MAP.get(key)
    if entry is None:
        logger.debug(
            "reputation.handle_mailgun_event: no counter mapping for %r — skipping",
            event_kind,
        )
        return
    redis_event, db_column = entry

    row = await _get_or_create_row(
        session,
        org_id=org_id,
        envelope_type=envelope_type,
        domain_id=domain_id,
    )

    await counters.incr_counter(
        org_id=org_id,
        envelope=envelope_type,
        domain_id=domain_id,
        event=redis_event,  # type: ignore[arg-type]  # Literal narrowed via _EVENT_MAP
    )

    if db_column is not None:
        await data_access.bump_db_mirror_counter(session, row_id=row.id, column=db_column, amount=1)

    await session.commit()


__all__ = ["handle_mailgun_event"]
