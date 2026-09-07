"""Data-access layer for the embed (widget) module.

Pure query helpers — no transactions, no audit, no bcrypt, no
business rules. Leaf module; never imports a ``service.py``.

Operations are grouped by entity:

  * Embed keys (``tbl_embed_keys``)
      get_embed_key_by_id, list_embed_keys,
      list_embed_keys_by_prefix_unrevoked,
      update_embed_key_last_used, insert_embed_key
  * Widget config (``tbl_widget_configs``)
      get_widget_config_for_org, insert_widget_config
  * Custom-field lookups against ``tbl_custom_field_definitions``
    (cross-module read; projection shape is widget-specific so it
    lives here rather than in custom_fields/data_access.py)
      list_custom_fields_for_widget_entities,
      list_custom_field_defs_by_keys
  * Submission logs (``tbl_embed_submission_logs``)
      insert_submission_log, list_submission_logs_query,
      submission_outcome_totals, submission_daily_outcome_buckets,
      delete_submission_logs_older_than
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.embed.models import (
    EmbedKey,
    EmbedSubmissionLog,
    EmbedSubmissionOutcome,
    WidgetConfig,
)

# --- Embed keys ---------------------------------------------------------


async def get_embed_key_by_id(session: AsyncSession, key_id: uuid.UUID) -> EmbedKey | None:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(select(EmbedKey).where(EmbedKey.id == key_id))
    ).scalar_one_or_none()


async def list_embed_keys(session: AsyncSession) -> list[EmbedKey]:
    """All embed keys for the active tenant (live + revoked), newest
    first. Owners see revoked keys too so they can audit who issued
    and revoked what."""
    rows = (
        (await session.execute(select(EmbedKey).order_by(EmbedKey.created_at.desc())))
        .scalars()
        .all()
    )
    return list(rows)


async def list_embed_keys_by_prefix_unrevoked(session: AsyncSession, prefix: str) -> list[EmbedKey]:
    """Candidates for the submission-path bcrypt verify. Filters to
    rows whose ``prefix`` matches and ``revoked_at IS NULL``. Caller
    opens the session OUTSIDE tenant context (the public endpoint has
    no JWT yet) so this is safe by design — the prefix is the
    caller-proved knowledge, bcrypt verify is the actual gate."""
    return list(
        (
            await session.execute(
                select(EmbedKey).where(
                    EmbedKey.prefix == prefix,
                    EmbedKey.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )


async def list_embed_keys_by_prefix_live(
    session: AsyncSession,
    *,
    prefix: str,
    now: datetime,
) -> list[EmbedKey]:
    """Like :func:`list_embed_keys_by_prefix_unrevoked` but includes
    rows whose ``revoked_at`` is set AS LONG AS ``grace_expires_at``
    hasn't elapsed yet. The public AI-assistants router uses this so
    a rotate-with-grace key keeps working for embedded snippets on
    external sites while the operator swaps in the new one.
    """
    return list(
        (
            await session.execute(
                select(EmbedKey).where(
                    EmbedKey.prefix == prefix,
                    sa.or_(
                        EmbedKey.revoked_at.is_(None),
                        sa.and_(
                            EmbedKey.grace_expires_at.isnot(None),
                            EmbedKey.grace_expires_at > now,
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )


async def update_embed_key_last_used(
    session: AsyncSession,
    *,
    key_id: uuid.UUID,
    when: datetime,
    ip_hash: str | None,
) -> None:
    """Fire-and-forget UPDATE of ``last_used_at`` + ``last_used_ip``
    after a successful submission match. Caller commits."""
    from sqlalchemy import update as sql_update

    await session.execute(
        sql_update(EmbedKey)
        .where(EmbedKey.id == key_id)
        .values(last_used_at=when, last_used_ip=ip_hash)
    )


def insert_embed_key(session: AsyncSession, key: EmbedKey) -> None:
    """Register an already-constructed EmbedKey for INSERT."""
    session.add(key)


# --- AI-assistant scoped helpers (Step 14) --------------------------------


async def list_embed_keys_for_resource(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
) -> list[EmbedKey]:
    """List keys scoped to one (resource_type, resource_id). Used by
    the operator UI's per-assistant Embed panel. Newest first, live +
    revoked both included."""
    rows = (
        (
            await session.execute(
                select(EmbedKey)
                .where(EmbedKey.resource_type == resource_type)
                .where(EmbedKey.resource_id == resource_id)
                .order_by(EmbedKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def set_grace_expiry(
    session: AsyncSession,
    *,
    key_id: uuid.UUID,
    revoked_at: datetime,
    revoked_by: uuid.UUID,
    grace_expires_at: datetime | None,
) -> None:
    """Set both ``revoked_at`` and ``grace_expires_at`` in one UPDATE
    so the rotate flow can't leave a key in a half-revoked state.
    ``grace_expires_at=None`` = immediate revoke."""
    from sqlalchemy import update as sql_update

    await session.execute(
        sql_update(EmbedKey)
        .where(EmbedKey.id == key_id)
        .values(
            revoked_at=revoked_at,
            revoked_by=revoked_by,
            grace_expires_at=grace_expires_at,
        )
    )


async def list_grace_expired(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 500,
) -> list[EmbedKey]:
    """Rows whose grace window has elapsed. Consumed by Step 17's
    sweeper which finalises the hard revoke (clears
    ``grace_expires_at`` so subsequent scans skip them). Bypasses
    tenant filter — the sweeper is cross-org by design."""
    rows = (
        (
            await session.execute(
                select(EmbedKey)
                .where(EmbedKey.grace_expires_at.isnot(None))
                .where(EmbedKey.grace_expires_at <= now)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def clear_grace_expiry(session: AsyncSession, key_id: uuid.UUID) -> None:
    """Zero out ``grace_expires_at`` after the sweeper has finalised
    a rotated key. Caller commits."""
    from sqlalchemy import update as sql_update

    await session.execute(
        sql_update(EmbedKey).where(EmbedKey.id == key_id).values(grace_expires_at=None)
    )


# --- Widget config ------------------------------------------------------


async def get_widget_config_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> WidgetConfig | None:
    """Resolve the org's DEFAULT widget form.

    Pre-0216 the table was one-row-per-org. Post-0216 an org may own
    many forms; this helper resolves the single form flagged
    ``is_default=true`` — the one every legacy embed snippet without
    a ``data-form`` attribute continues to resolve to. Soft-deleted
    rows are excluded so an admin who retires a default form doesn't
    keep serving its config.

    Used by both the authed Settings → Widget read (via
    ``get_or_create``) AND the public submission / config endpoints
    (the public caller bypasses tenant context — the explicit
    ``WHERE org_id = ...`` is the authorisation gate).
    """
    return (
        await session.execute(
            select(WidgetConfig)
            .where(WidgetConfig.org_id == org_id)
            .where(WidgetConfig.is_default.is_(True))
            .where(WidgetConfig.deleted_at.is_(None))
            .limit(1)
        )
    ).scalar_one_or_none()


def insert_widget_config(session: AsyncSession, config: WidgetConfig) -> None:
    """Register an already-constructed WidgetConfig for INSERT."""
    session.add(config)


# --- Custom-field lookups (cross-module read) ---------------------------


async def list_custom_fields_for_widget_entities(
    session: AsyncSession,
    *,
    entity_types: tuple[str, ...],
) -> list[CustomFieldDefinition]:
    """Visible custom fields the widget Settings picker can offer for
    opt-in, scoped to ``entity_types`` (``contact``, ``lead``). Ordered
    by entity then display order for stable picker rendering.

    Hidden rows are excluded — the picker only shows opt-in candidates.
    """
    return list(
        (
            await session.execute(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.entity_type.in_(entity_types))
                .where(CustomFieldDefinition.is_hidden.is_(False))
                .order_by(
                    CustomFieldDefinition.entity_type,
                    CustomFieldDefinition.display_order,
                )
            )
        )
        .scalars()
        .all()
    )


async def list_custom_field_defs_by_keys(
    session: AsyncSession,
    *,
    entity_types: tuple[str, ...],
    field_keys: list[str],
) -> list[CustomFieldDefinition]:
    """Lookup definitions matching ``entity_types`` AND ``field_keys``
    — used by the widget-config update validator to confirm every
    custom-source field reference actually exists. Hidden rows ARE
    included here because validation runs before the picker UX
    filters anything out."""
    return list(
        (
            await session.execute(
                select(CustomFieldDefinition).where(
                    CustomFieldDefinition.entity_type.in_(entity_types),
                    CustomFieldDefinition.field_key.in_(field_keys),
                )
            )
        )
        .scalars()
        .all()
    )


# --- Submission logs ----------------------------------------------------


def insert_submission_log(session: AsyncSession, row: EmbedSubmissionLog) -> None:
    """Register an already-constructed EmbedSubmissionLog for INSERT."""
    session.add(row)


async def list_submission_logs_query(
    session: AsyncSession,
    *,
    outcome: EmbedSubmissionOutcome | None = None,
    range_from: datetime | None = None,
    range_to: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[EmbedSubmissionLog], int]:
    """Paginated list of submission logs (newest first). Tenant
    scoping is automatic via the ORM filter on ``TenantScoped``."""
    base = select(EmbedSubmissionLog)
    if outcome is not None:
        base = base.where(EmbedSubmissionLog.outcome == outcome)
    if range_from is not None:
        base = base.where(EmbedSubmissionLog.created_at >= range_from)
    if range_to is not None:
        base = base.where(EmbedSubmissionLog.created_at <= range_to)

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    offset = (page - 1) * page_size
    rows = (
        (
            await session.execute(
                base.order_by(EmbedSubmissionLog.created_at.desc()).offset(offset).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def submission_outcome_totals(
    session: AsyncSession,
    *,
    range_from: datetime,
    range_to: datetime,
) -> list[Row]:
    """GROUP BY outcome over ``[range_from, range_to]``. Returns
    ``[(outcome, count), ...]``."""
    return list(
        (
            await session.execute(
                select(
                    EmbedSubmissionLog.outcome,
                    func.count(EmbedSubmissionLog.id),
                )
                .where(EmbedSubmissionLog.created_at >= range_from)
                .where(EmbedSubmissionLog.created_at <= range_to)
                .group_by(EmbedSubmissionLog.outcome)
            )
        ).all()
    )


async def submission_daily_outcome_buckets(
    session: AsyncSession,
    *,
    range_from: datetime,
    range_to: datetime,
) -> list[Row]:
    """``date_trunc('day', created_at)`` × outcome rollup. Returns
    ``[(day, outcome, count), ...]``."""
    return list(
        (
            await session.execute(
                select(
                    func.date_trunc("day", EmbedSubmissionLog.created_at).label("day"),
                    EmbedSubmissionLog.outcome,
                    func.count(EmbedSubmissionLog.id),
                )
                .where(EmbedSubmissionLog.created_at >= range_from)
                .where(EmbedSubmissionLog.created_at <= range_to)
                .group_by("day", EmbedSubmissionLog.outcome)
            )
        ).all()
    )


async def delete_submission_logs_older_than(session: AsyncSession, cutoff: datetime) -> int:
    """Bulk DELETE older than ``cutoff``. Returns the row count
    purged. Caller commits."""
    result = await session.execute(
        delete(EmbedSubmissionLog).where(EmbedSubmissionLog.created_at < cutoff)
    )
    return int(result.rowcount or 0)


__all__ = [
    "delete_submission_logs_older_than",
    "get_embed_key_by_id",
    "get_widget_config_for_org",
    "insert_embed_key",
    "insert_submission_log",
    "insert_widget_config",
    "list_custom_field_defs_by_keys",
    "clear_grace_expiry",
    "list_custom_fields_for_widget_entities",
    "list_embed_keys",
    "list_embed_keys_by_prefix_live",
    "list_embed_keys_by_prefix_unrevoked",
    "list_embed_keys_for_resource",
    "list_grace_expired",
    "list_submission_logs_query",
    "set_grace_expiry",
    "submission_daily_outcome_buckets",
    "submission_outcome_totals",
    "update_embed_key_last_used",
]
