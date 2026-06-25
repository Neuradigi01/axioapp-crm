"""Data-access layer for the pipelines module.

Pure query helpers — no transactions, no audit, no allowlist
validation. Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Pipelines / Stages (``tbl_pipelines``, ``tbl_pipeline_stages``)
      list_pipelines_with_stages, get_pipeline_by_key_with_stages,
      get_pipeline_by_id_with_stages, get_stage_by_id,
      find_stage_at_order, insert_pipeline_stage,
      delete_pipeline_stage_row
  * Pipeline-tracked card tables (raw SQL via ``text()``)
      read_card_pipeline_stage, update_card_pipeline_stage,
      count_cards_in_stage_for_table,
      relocate_cards_for_table

**Table-name safety:** every function that interpolates a table name
into a raw SQL string trusts the caller (``service.py``) to have
validated the name against the ``_PIPELINE_TRACKED_TABLES`` registry
+ the ``_TABLE_NAME_RE`` regex. The DAL re-checks the regex as a
second line of defence.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.core.pipelines.models import Pipeline, PipelineStage


# Same identifier pattern the service registry enforces; re-checked
# here so a typo / direct call from outside still can't slip a
# malicious table name into the f-string.
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _validated_table(table: str) -> str:
    """Validate ``table`` against the SQL-safe identifier pattern.
    Raises ``ValueError`` on a bad name — the service should have
    rejected it upstream."""
    if not _TABLE_NAME_RE.match(table):
        raise ValueError(
            f"pipeline-tracked table name {table!r} must match "
            "[a-z][a-z0-9_]*"
        )
    return table


def _pipeline_select_with_stages():
    """Reusable base SELECT that eager-loads ``Pipeline.stages``."""
    return select(Pipeline).options(selectinload(Pipeline.stages))


# --- Pipelines / Stages -------------------------------------------------


async def list_pipelines_with_stages(
    session: AsyncSession,
) -> list[Pipeline]:
    """All pipelines for the active tenant, stages eager-loaded,
    ordered by name."""
    result = await session.execute(
        _pipeline_select_with_stages().order_by(Pipeline.name)
    )
    return list(result.scalars().all())


async def get_pipeline_by_key_with_stages(
    session: AsyncSession, key: str
) -> Optional[Pipeline]:
    """Single pipeline by ``key`` with stages eager-loaded."""
    result = await session.execute(
        _pipeline_select_with_stages().where(Pipeline.key == key)
    )
    return result.scalar_one_or_none()


async def get_pipeline_by_id_with_stages(
    session: AsyncSession, pipeline_id: uuid.UUID
) -> Optional[Pipeline]:
    """Single pipeline by PK with stages eager-loaded."""
    result = await session.execute(
        _pipeline_select_with_stages().where(Pipeline.id == pipeline_id)
    )
    return result.scalar_one_or_none()


async def get_stage_by_id(
    session: AsyncSession, stage_id: uuid.UUID
) -> Optional[PipelineStage]:
    """Single PipelineStage by PK."""
    result = await session.execute(
        select(PipelineStage).where(PipelineStage.id == stage_id)
    )
    return result.scalar_one_or_none()


async def find_stage_at_order(
    session: AsyncSession,
    *,
    pipeline_id: uuid.UUID,
    display_order: int,
    exclude_id: uuid.UUID,
) -> Optional[PipelineStage]:
    """Locate the stage that currently holds ``display_order`` in
    ``pipeline_id``, excluding the row being updated. Used by the
    swap-orders logic in ``update_stage``."""
    return (
        await session.execute(
            select(PipelineStage)
            .where(PipelineStage.pipeline_id == pipeline_id)
            .where(PipelineStage.display_order == display_order)
            .where(PipelineStage.id != exclude_id)
        )
    ).scalar_one_or_none()


def insert_pipeline_stage(
    session: AsyncSession, stage: PipelineStage
) -> None:
    """Register an already-constructed PipelineStage for INSERT."""
    session.add(stage)


async def delete_pipeline_stage_row(
    session: AsyncSession, stage: PipelineStage
) -> None:
    """Mark a PipelineStage row for DELETE. Caller commits."""
    await session.delete(stage)


# --- Pipeline-tracked card tables (raw SQL) -----------------------------


async def read_card_pipeline_stage(
    session: AsyncSession,
    *,
    table: str,
    card_id: uuid.UUID,
) -> Optional[str]:
    """Read the ``pipeline_stage`` value for one row in a pipeline-
    tracked table. Returns ``None`` when the row doesn't exist."""
    safe_table = _validated_table(table)
    row = (
        await session.execute(
            text(
                f"SELECT pipeline_stage FROM {safe_table} "
                "WHERE id = :card_id"
            ),
            {"card_id": card_id},
        )
    ).first()
    return None if row is None else row[0]


async def update_card_pipeline_stage(
    session: AsyncSession,
    *,
    table: str,
    card_id: uuid.UUID,
    to_key: str,
) -> None:
    """UPDATE one row's ``pipeline_stage`` + ``updated_at`` in a
    pipeline-tracked table. Caller commits."""
    safe_table = _validated_table(table)
    await session.execute(
        text(
            f"UPDATE {safe_table} SET pipeline_stage = :to_key, "
            "updated_at = now() WHERE id = :card_id"
        ),
        {"to_key": to_key, "card_id": card_id},
    )


async def count_cards_in_stage_for_table(
    session: AsyncSession,
    *,
    table: str,
    key: str,
) -> int:
    """COUNT rows whose ``pipeline_stage = key`` in a pipeline-tracked
    table. Used by the delete-stage guard to decide whether to refuse
    409 or relocate."""
    safe_table = _validated_table(table)
    row = (
        await session.execute(
            text(
                f"SELECT count(*) FROM {safe_table} "
                "WHERE pipeline_stage = :key"
            ),
            {"key": key},
        )
    ).first()
    return 0 if row is None else int(row[0])


async def relocate_cards_for_table(
    session: AsyncSession,
    *,
    table: str,
    from_key: str,
    to_key: str,
) -> int:
    """UPDATE every row whose ``pipeline_stage = from_key`` in a
    pipeline-tracked table to ``to_key`` + stamp ``updated_at``.
    Returns the affected row count. Caller commits."""
    safe_table = _validated_table(table)
    result = await session.execute(
        text(
            f"UPDATE {safe_table} SET pipeline_stage = :to_key, "
            "updated_at = now() WHERE pipeline_stage = :from_key"
        ),
        {"to_key": to_key, "from_key": from_key},
    )
    return int(result.rowcount or 0)


__all__ = [
    "count_cards_in_stage_for_table",
    "delete_pipeline_stage_row",
    "find_stage_at_order",
    "get_pipeline_by_id_with_stages",
    "get_pipeline_by_key_with_stages",
    "get_stage_by_id",
    "insert_pipeline_stage",
    "list_pipelines_with_stages",
    "read_card_pipeline_stage",
    "relocate_cards_for_table",
    "update_card_pipeline_stage",
]
