"""Service layer for the pipelines engine.

Four public entry points:

- **`list_pipelines`** / **`get_pipeline_by_key`** — reads with eager-loaded
  stages, ordered by `display_order`.
- **`update_stage`** — applies label/color/order edits. When the caller
  changes `display_order` and the slot is taken, the existing stage at
  that slot is moved into the vacated slot ("trade places"). Both
  updates happen in one transaction; the `(pipeline_id, display_order)`
  unique constraint is `INITIALLY DEFERRED` so the mid-statement
  collision is fine.
- **`move_card`** — generic helper any pipeline-tracked entity (Leads
  in 2.11, Custom Orders in 4.8) calls to change its `pipeline_stage`
  column. Writes both an activity row (`type='status_change'`) and an
  audit log. Card tables register themselves with
  `register_pipeline_table('leads')` so the helper never executes raw
  SQL against an unknown table name.

`register_pipeline_table` is the registry mechanism for the allowlist
— modules call it at import time. We do NOT pre-populate any names
here, because doing so would re-introduce the cross-layer knowledge
the registry is designed to avoid.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.core import activities, audit
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.pipelines.schemas import StageUpdate

logger = logging.getLogger(__name__)


# Modules that own pipeline-tracked tables call register_pipeline_table()
# from their __init__.py at import time. Empty by default — Step 2.11
# (Leads) is the first known consumer.
_PIPELINE_TRACKED_TABLES: set[str] = set()

# Defensive: only allow simple ASCII identifiers as registered table
# names. The names land inside a raw SQL UPDATE, so this is the second
# line of defence after the registry check.
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def register_pipeline_table(name: str) -> None:
    """Register a table name that `move_card` is allowed to UPDATE.

    Modules call this on import. Idempotent. Raises ValueError if the
    name doesn't match the SQL-safe identifier pattern, because we
    interpolate it into the UPDATE statement (bind params can't carry
    a table name).
    """
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(
            f"pipeline-tracked table name {name!r} must match [a-z][a-z0-9_]*"
        )
    _PIPELINE_TRACKED_TABLES.add(name)


def _pipeline_select_with_stages():
    return select(Pipeline).options(selectinload(Pipeline.stages))


async def list_pipelines(session: AsyncSession) -> list[Pipeline]:
    result = await session.execute(
        _pipeline_select_with_stages().order_by(Pipeline.name)
    )
    return list(result.scalars().all())


async def get_pipeline_by_key(
    session: AsyncSession, *, key: str
) -> Optional[Pipeline]:
    result = await session.execute(
        _pipeline_select_with_stages().where(Pipeline.key == key)
    )
    return result.scalar_one_or_none()


async def get_pipeline_by_id(
    session: AsyncSession, *, pipeline_id: uuid.UUID
) -> Optional[Pipeline]:
    result = await session.execute(
        _pipeline_select_with_stages().where(Pipeline.id == pipeline_id)
    )
    return result.scalar_one_or_none()


async def get_stage(
    session: AsyncSession, stage_id: uuid.UUID
) -> Optional[PipelineStage]:
    result = await session.execute(
        select(PipelineStage).where(PipelineStage.id == stage_id)
    )
    return result.scalar_one_or_none()


def _stage_snapshot(s: PipelineStage) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "pipeline_id": str(s.pipeline_id),
        "key": s.key,
        "name": s.name,
        "color": s.color,
        "display_order": s.display_order,
        "is_won": s.is_won,
        "is_lost": s.is_lost,
    }


async def update_stage(
    session: AsyncSession,
    *,
    pipeline_key: str,
    stage_id: uuid.UUID,
    payload: StageUpdate,
) -> PipelineStage:
    """Update label / color / display_order on one stage.

    If `display_order` is changing and the target slot is occupied by
    another stage in the same pipeline, we swap: the other stage gets
    the vacated slot. The deferred unique constraint allows the swap to
    proceed in one transaction without an intermediate constraint break.
    """
    pipeline = await get_pipeline_by_key(session, key=pipeline_key)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="pipeline not found"
        )

    stage = await get_stage(session, stage_id)
    if stage is None or stage.pipeline_id != pipeline.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="stage not found in this pipeline",
        )

    before = _stage_snapshot(stage)
    changes = payload.model_dump(exclude_unset=True)

    if "display_order" in changes:
        new_order = changes["display_order"]
        if new_order != stage.display_order:
            existing = (
                await session.execute(
                    select(PipelineStage)
                    .where(PipelineStage.pipeline_id == pipeline.id)
                    .where(PipelineStage.display_order == new_order)
                    .where(PipelineStage.id != stage.id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                # "Trade places": existing stage takes the vacated slot.
                existing.display_order = stage.display_order
                session.add(existing)

    for key, value in changes.items():
        setattr(stage, key, value)
    await session.commit()
    await session.refresh(stage)

    await audit.log(
        "pipelines.stage_updated",
        entity_type="pipeline_stage",
        entity_id=stage.id,
        before=before,
        after=_stage_snapshot(stage),
    )
    return stage


async def move_card(
    session: AsyncSession,
    *,
    pipeline_key: str,
    card_table: str,
    card_id: uuid.UUID,
    to_stage_key: str,
    user_id: Optional[uuid.UUID] = None,
) -> None:
    """Generic helper: move a row in `card_table` to `to_stage_key`.

    Validates that:
      1. The table name is registered (`register_pipeline_table`).
      2. The pipeline exists in this tenant.
      3. The target stage key exists in that pipeline.

    Then UPDATEs `card_table.pipeline_stage = :to_stage_key` for the
    given `card_id`, writes a `status_change` activity, and an audit
    log carrying before/after stage keys.

    The caller's session is used for the UPDATE so the change shares
    the request's transaction; the activity + audit writes are
    intentionally best-effort (they use their own sessions).
    """
    if card_table not in _PIPELINE_TRACKED_TABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"card_table {card_table!r} is not a registered "
                "pipeline-tracked table"
            ),
        )

    pipeline = await get_pipeline_by_key(session, key=pipeline_key)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline {pipeline_key!r} not found",
        )

    valid_stage_keys = {s.key for s in pipeline.stages}
    if to_stage_key not in valid_stage_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"stage {to_stage_key!r} is not part of pipeline "
                f"{pipeline_key!r}"
            ),
        )

    # Read current stage first so we can stamp before/after on audit.
    # `card_table` is whitelisted above so f-string interpolation is safe;
    # `card_id` is bound as a parameter (asyncpg coerces uuid.UUID natively).
    current_row = (
        await session.execute(
            text(
                f"SELECT pipeline_stage FROM {card_table} WHERE id = :card_id"  # noqa: S608
            ),
            {"card_id": card_id},
        )
    ).first()
    if current_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{card_table} row {card_id} not found",
        )
    from_stage_key = current_row[0]

    if from_stage_key == to_stage_key:
        # Idempotent: nothing to log.
        return

    await session.execute(
        text(
            f"UPDATE {card_table} SET pipeline_stage = :to_key, "  # noqa: S608
            "updated_at = now() WHERE id = :card_id"
        ),
        {"to_key": to_stage_key, "card_id": card_id},
    )
    await session.commit()

    await activities.log(
        entity_type=card_table,
        entity_id=card_id,
        type=activities.ActivityType.status_change,
        payload={
            "pipeline": pipeline_key,
            "from": from_stage_key,
            "to": to_stage_key,
        },
        user_id=user_id,
    )
    await audit.log(
        "pipelines.card_moved",
        entity_type=card_table,
        entity_id=card_id,
        before={"pipeline": pipeline_key, "stage": from_stage_key},
        after={"pipeline": pipeline_key, "stage": to_stage_key},
        user_id=user_id,
    )


__all__ = [
    "get_pipeline_by_id",
    "get_pipeline_by_key",
    "get_stage",
    "list_pipelines",
    "move_card",
    "register_pipeline_table",
    "update_stage",
]
