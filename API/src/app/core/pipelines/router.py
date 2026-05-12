"""HTTP routes for the pipelines engine.

  GET   /api/v1/pipelines                          → list pipelines
  GET   /api/v1/pipelines/{key}                    → one pipeline + stages
  PATCH /api/v1/pipelines/{key}/stages/{stage_id}  → name/color/order

Read gates by `pipelines.read`; updates by `pipelines.manage`. The
move-card flow has no HTTP surface in this step — `pipelines.move_card`
is consumed in-process by Leads / Custom Orders routers in later steps.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.pipelines.schemas import (
    PipelineOut,
    PipelineStageOut,
    StageUpdate,
)
from src.app.core.pipelines.service import (
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
