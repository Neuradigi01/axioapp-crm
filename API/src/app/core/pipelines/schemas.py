"""Pydantic v2 schemas for the pipelines engine.

`StageUpdate` deliberately omits `key`, `is_won`, and `is_lost` — those
are pack-defined invariants per the master prompt and must not change
through the HTTP edit surface. The PATCH endpoint accepts at most
label/color/order; trying to PATCH anything else gets a 422 because
Pydantic refuses unknown keys by default.

`StageCreate` mirrors that policy for POST: callers supply `name`
(slugified to derive `key`), optional `color`, and optional
`after_stage_key` to control placement. `is_won`/`is_lost` are not
acceptable — creating terminal stages from the API is a pack-level
concern, so they're hardcoded to `false` in the service.
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


class StageCreate(BaseModel):
    """Inputs for POST /pipelines/{key}/stages.

    `name` is required; the service slugifies it to derive `key`.
    `after_stage_key`, when provided, inserts the new stage immediately
    after that stage and shifts every later stage's `display_order` up
    by 1. When omitted, the new stage is appended at the end.
    `is_won`/`is_lost` are not accepted (extra='forbid').
    """

    name: str = Field(min_length=1, max_length=128)
    color: Optional[str] = Field(default=None, max_length=16)
    after_stage_key: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
