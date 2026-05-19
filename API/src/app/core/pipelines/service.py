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
from src.app.core.pipelines.schemas import StageCreate, StageUpdate

logger = logging.getLogger(__name__)


# Modules that own pipeline-tracked tables call register_pipeline_table()
# from their __init__.py at import time. Empty by default — Step 2.11
# (Leads) is the first known consumer.
_PIPELINE_TRACKED_TABLES: set[str] = set()

# Defensive: only allow simple ASCII identifiers as registered table
# names. The names land inside a raw SQL UPDATE, so this is the second
# line of defence after the registry check.
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Slug derivation for new stage keys: lowercase, collapse runs of
# non-alphanumerics into a single underscore, trim leading/trailing
# underscores. Length-capped to fit the `key VARCHAR(64)` column.
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify_stage_key(name: str) -> str:
    s = _SLUG_NON_ALNUM_RE.sub("_", name.lower()).strip("_")
    return s[:64]


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


async def create_stage(
    session: AsyncSession,
    *,
    pipeline_key: str,
    payload: StageCreate,
) -> PipelineStage:
    """Insert a new stage into `pipeline_key`.

    - Slugifies `payload.name` to derive `key`; rejects 422 if empty or
      collides with an existing stage in this pipeline.
    - If `after_stage_key` is given, places the new stage at
      `that_stage.display_order + 1` and shifts every later stage's
      order up by 1 (deferred-unique constraint absorbs the mid-txn
      collision); otherwise appends at the end.
    - `is_won`/`is_lost` are hardcoded `False`: creating terminal
      stages from the API is a pack-level concern.
    """
    pipeline = await get_pipeline_by_key(session, key=pipeline_key)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="pipeline not found"
        )

    new_key = _slugify_stage_key(payload.name)
    if not new_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name does not yield a valid stage key after slugification",
        )

    existing_keys = {s.key for s in pipeline.stages}
    if new_key in existing_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"stage key {new_key!r} already exists in this pipeline",
        )

    if payload.after_stage_key is not None:
        anchor = next(
            (s for s in pipeline.stages if s.key == payload.after_stage_key),
            None,
        )
        if anchor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"after_stage_key {payload.after_stage_key!r} is not a "
                    f"stage in pipeline {pipeline_key!r}"
                ),
            )
        insert_at = anchor.display_order + 1
        # Shift every stage at or beyond the new slot up by 1. The
        # `(pipeline_id, display_order)` unique constraint is INITIALLY
        # DEFERRED so the mid-statement collision is acceptable.
        for s in pipeline.stages:
            if s.display_order >= insert_at:
                s.display_order = s.display_order + 1
                session.add(s)
    else:
        max_order = max((s.display_order for s in pipeline.stages), default=-1)
        insert_at = max_order + 1

    stage = PipelineStage(
        org_id=pipeline.org_id,
        pipeline_id=pipeline.id,
        key=new_key,
        name=payload.name,
        color=payload.color,
        display_order=insert_at,
        is_won=False,
        is_lost=False,
    )
    session.add(stage)
    await session.commit()
    await session.refresh(stage)

    await audit.log(
        "pipelines.stage_created",
        entity_type="pipeline_stage",
        entity_id=stage.id,
        after=_stage_snapshot(stage),
    )
    return stage


async def delete_stage(
    session: AsyncSession,
    *,
    pipeline_key: str,
    stage_id: uuid.UUID,
    move_leads_to: Optional[str] = None,
) -> None:
    """Delete a stage, relocating any cards that reference its key.

    Rules:
      - Terminal stages (`is_won` / `is_lost`) cannot be deleted (409).
      - Counts rows in every registered pipeline-tracked table where
        `pipeline_stage = stage.key`. If the count is non-zero and
        `move_leads_to` is not supplied, 409 with
        `{cards_in_stage, must_provide}`.
      - When relocation is supplied, UPDATEs all those rows to the
        target stage's key, then DELETEs the stage — both in the
        caller's transaction.
      - `display_order` gaps on remaining stages are accepted.
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

    if stage.is_won or stage.is_lost:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot delete a won/lost stage",
        )

    if move_leads_to is not None:
        if move_leads_to == stage.key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="move_leads_to cannot be the stage being deleted",
            )
        target_exists = any(
            s.key == move_leads_to for s in pipeline.stages
        )
        if not target_exists:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"move_leads_to {move_leads_to!r} is not a stage in "
                    f"pipeline {pipeline_key!r}"
                ),
            )

    # Tally cards across every registered pipeline-tracked table.
    # `_PIPELINE_TRACKED_TABLES` only ever holds names that passed the
    # `_TABLE_NAME_RE` allowlist, so f-string interpolation is safe here.
    cards_in_stage = 0
    for table in _PIPELINE_TRACKED_TABLES:
        row = (
            await session.execute(
                text(
                    f"SELECT count(*) FROM {table} "  # noqa: S608
                    "WHERE pipeline_stage = :key"
                ),
                {"key": stage.key},
            )
        ).first()
        if row is not None:
            cards_in_stage += int(row[0])

    if cards_in_stage > 0 and move_leads_to is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "cards_in_stage": cards_in_stage,
                "must_provide": "move_leads_to",
            },
        )

    before = _stage_snapshot(stage)
    cards_moved_count = 0
    if cards_in_stage > 0 and move_leads_to is not None:
        for table in _PIPELINE_TRACKED_TABLES:
            result = await session.execute(
                text(
                    f"UPDATE {table} SET pipeline_stage = :to_key, "  # noqa: S608
                    "updated_at = now() WHERE pipeline_stage = :from_key"
                ),
                {"to_key": move_leads_to, "from_key": stage.key},
            )
            cards_moved_count += result.rowcount or 0

    await session.delete(stage)
    await session.commit()

    await audit.log(
        "pipelines.stage_deleted",
        entity_type="pipeline_stage",
        entity_id=stage_id,
        before=before,
        after={
            "cards_moved_count": cards_moved_count,
            "cards_moved_to": move_leads_to,
        },
    )


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
    "create_stage",
    "delete_stage",
    "get_pipeline_by_id",
    "get_pipeline_by_key",
    "get_stage",
    "list_pipelines",
    "move_card",
    "register_pipeline_table",
    "update_stage",
]
