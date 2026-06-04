"""Pydantic models for the pack catalog endpoint."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PackStatus = Literal["available", "coming_soon"]


class CatalogTile(BaseModel):
    """One tile shown on the onboarding template picker."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    icon: str = Field(min_length=1, max_length=64)
    status: PackStatus
    default_currency: str = Field(min_length=3, max_length=3)
    default_tax_rate: float = Field(ge=0, le=100)
    modules_preview: list[str] = Field(default_factory=list)
    display_order: int = Field(ge=0)


class CatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Kept as `packs` (not `templates`) because the catalog still
    # serves a list of "packs" (the folder structure / module name)
    # which now identify themselves by template_id. Renaming the JSON
    # response key would force every frontend consumer to migrate; the
    # value type itself carries the rename.
    packs: list[CatalogTile]


__all__ = ["CatalogResponse", "CatalogTile", "PackStatus"]
