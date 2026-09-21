"""Pure CRUD for ``tbl_organization_email_reputation``.

Two responsibilities:

  * :func:`get_row` / :func:`insert_row` — point-read + INSERT for the
    (org × envelope × domain) tuple. The events-webhook task calls
    :func:`get_or_create_row` (thin service-side wrapper — kept here
    beside the DAL primitives for readability, but does NOT commit).
  * :func:`bump_db_mirror_counter` — increments the ``bounce_count_24h``
    / ``complaint_count_24h`` / ``delivered_count_24h`` columns on the
    reputation row. These are convenience mirrors of the Redis 24h
    buckets so the dashboard doesn't need a Redis round-trip; Redis
    is still the source of truth (:mod:`.counters`).

DAL discipline (memory ``feedback_backend_layered_architecture.md``):
no ``session.commit / flush / refresh / rollback`` here — those live
in ``service.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation.models import OrganizationEmailReputation


async def get_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> OrganizationEmailReputation | None:
    """Point-read the reputation row for one (org × envelope × domain)
    tuple. Returns ``None`` if the row hasn't been created yet — the
    first event for that envelope triggers the INSERT via
    :func:`insert_row`.

    ``domain_id`` is NULL for ``platform_from`` and non-NULL for
    ``own_domain``; the shape CHECK on the migration enforces this
    invariant. This helper mirrors the shape — an ``own_domain`` call
    with ``domain_id=None`` returns ``None`` (no matching row), never
    a spurious platform_from hit.
    """
    stmt = select(OrganizationEmailReputation).where(
        OrganizationEmailReputation.org_id == org_id,
        OrganizationEmailReputation.envelope_type == envelope_type,
    )
    if domain_id is None:
        stmt = stmt.where(OrganizationEmailReputation.domain_id.is_(None))
    else:
        stmt = stmt.where(OrganizationEmailReputation.domain_id == domain_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def insert_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> OrganizationEmailReputation:
    """Stage an INSERT for a fresh reputation row. Server defaults
    fill in ``warmup_stage=0``, ``reputation_state='ok'`` and the
    24h counter mirrors at 0. Caller commits.

    Race note: two concurrent events for the same (org, envelope,
    domain) can both find no row + both stage an INSERT. Postgres'
    partial unique index catches the second on commit — the caller
    must retry the lookup path on ``IntegrityError``. See
    :func:`service.get_or_create_row_atomic` for the retry loop.
    """
    row = OrganizationEmailReputation(
        org_id=org_id,
        envelope_type=envelope_type,
        domain_id=domain_id,
    )
    session.add(row)
    return row


async def bump_db_mirror_counter(
    session: AsyncSession,
    *,
    row_id: uuid.UUID,
    column: str,
    amount: int = 1,
) -> None:
    """Increment one of the ``*_count_24h`` mirror columns by
    ``amount``. Called after the Redis counter INCR so the dashboard
    read reflects the same value.

    ``column`` MUST be one of:
      * ``bounce_count_24h``
      * ``complaint_count_24h``
      * ``delivered_count_24h``

    Any other value is a caller bug — raise ``ValueError`` rather
    than silently no-op'ing (a typo'd column would drop the counter).
    """
    allowed = {"bounce_count_24h", "complaint_count_24h", "delivered_count_24h"}
    if column not in allowed:
        raise ValueError(
            f"bump_db_mirror_counter: unknown column {column!r}; allowed: {sorted(allowed)}"
        )
    stmt = (
        update(OrganizationEmailReputation)
        .where(OrganizationEmailReputation.id == row_id)
        .values({column: OrganizationEmailReputation.__table__.c[column] + amount})
    )
    await session.execute(stmt)


__all__ = [
    "bump_db_mirror_counter",
    "get_row",
    "insert_row",
]
