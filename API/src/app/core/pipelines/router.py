"""HTTP routes for the pipelines engine.

  GET    /api/v1/pipelines                          → list pipelines
  GET    /api/v1/pipelines/{key}                    → one pipeline + stages
  POST   /api/v1/pipelines/{key}/stages             → add a new stage
  PATCH  /api/v1/pipelines/{key}/stages/{stage_id}  → name/color/order
  DELETE /api/v1/pipelines/{key}/stages/{stage_id}  → remove (relocate cards)

Read gates by `pipelines.read`; mutations by `pipelines.manage`. The
move-card flow has no HTTP surface in this step — `pipelines.move_card`
is consumed in-process by Leads / Custom Orders routers in later steps.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.pipelines.schemas import (
    PipelineOut,
    PipelineStageOut,
    StageCreate,
    StageUpdate,
)
from src.app.core.pipelines.service import (
    create_stage,
    delete_stage,
    get_pipeline_by_key,
    list_pipelines,
    update_stage,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


@router.get("", response_model=list[PipelineOut])
async def list_pipelines_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("pipelines.read")),
) -> list[PipelineOut]:
    rows = await list_pipelines(db)
    return [PipelineOut.model_validate(p) for p in rows]


@router.get("/{pipeline_key}", response_model=PipelineOut)
async def get_pipeline_endpoint(
    pipeline_key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("pipelines.read")),
) -> PipelineOut:
    pipeline = await get_pipeline_by_key(db, key=pipeline_key)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pipeline {pipeline_key!r} not found",
        )
    return PipelineOut.model_validate(pipeline)


@router.post(
    "/{pipeline_key}/stages",
    response_model=PipelineStageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_stage_endpoint(
    pipeline_key: str,
    payload: StageCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("pipelines.manage")),
) -> PipelineStageOut:
    stage = await create_stage(
        db, pipeline_key=pipeline_key, payload=payload
    )
    return PipelineStageOut.model_validate(stage)


@router.patch(
    "/{pipeline_key}/stages/{stage_id}", response_model=PipelineStageOut
)
async def update_stage_endpoint(
    pipeline_key: str,
    stage_id: uuid.UUID,
    payload: StageUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("pipelines.manage")),
) -> PipelineStageOut:
    stage = await update_stage(
        db, pipeline_key=pipeline_key, stage_id=stage_id, payload=payload
    )
    return PipelineStageOut.model_validate(stage)


@router.delete(
    "/{pipeline_key}/stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_stage_endpoint(
    pipeline_key: str,
    stage_id: uuid.UUID,
    move_leads_to: str | None = Query(default=None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("pipelines.manage")),
) -> Response:
    await delete_stage(
        db,
        pipeline_key=pipeline_key,
        stage_id=stage_id,
        move_leads_to=move_leads_to,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
