"""Pydantic v2 schemas for the pipelines engine.

`StageUpdate` deliberately omits `key`, `is_won`, and `is_lost` — those
are pack-defined invariants per the master prompt and must not change
through the HTTP edit surface. The PATCH endpoint accepts at most
label/color/order; trying to PATCH anything else gets a 422 because
Pydantic refuses unknown keys by default.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PipelineStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_id: uuid.UUID
    key: str
    name: str
    color: Optional[str]
    display_order: int
    is_won: bool
    is_lost: bool


class PipelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    key: str
    name: str
    created_at: datetime
    stages: list[PipelineStageOut]


class StageUpdate(BaseModel):
    """Editable fields only — label, color, display_order."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    color: Optional[str] = Field(default=None, max_length=16)
    display_order: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
