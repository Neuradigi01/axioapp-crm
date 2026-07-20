"""Pydantic v2 schemas for `saved_views`.

The schema deliberately keeps ``config.filter`` typed as a free-form
``dict`` rather than importing the leads filter DSL — the saved_views
module is generic infrastructure that the leads page (and future list
pages) layers on top of. Semantic validation of ``config.filter``
lives in the consuming page, not here.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import TimestampedOrgScopedOut


class SavedViewConfig(BaseModel):
    """Configuration bundle a saved view restores.

    Every field is optional individually — missing keys mean "use the
    page default." The FE chooses which keys it cares about per entity
    (the leads page reads filter/sort/order/scope/columns/view; future
    pages can subset).
    """

    model_config = ConfigDict(extra="forbid")

    # Filter DSL fragment. Free-form here; the leads page validates
    # shape via `core/leads/filter_dsl.parse()` before applying.
    filter: dict[str, Any] | None = None
    sort: str | None = Field(default=None, max_length=64)
    order: Literal["asc", "desc"] | None = None
    scope: Literal["mine", "team", "all"] | None = None
    # List of column descriptors as the FE persists them (key / label /
    # visible). Order matters: array order = column display order.
    columns: list[dict[str, Any]] | None = None
    view: Literal["list", "pipeline"] | None = None


class SavedViewCreate(BaseModel):
    # Widen further when walk-ins / appointments wire their saved-views
    # toolbars. Tasks live here as of the T15 tasks-review fix.
    entity: Literal["leads", "contacts", "tasks"]
    name: str = Field(min_length=1, max_length=80)
    config: SavedViewConfig
    shared: bool = False

    model_config = ConfigDict(str_strip_whitespace=True)


class SavedViewUpdate(BaseModel):
    """Partial update. Each field is optional; entity is immutable
    (rename across entities makes no sense — make a new view)."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: SavedViewConfig | None = None
    shared: bool | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class SavedViewOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    entity: str
    name: str
    config: dict[str, Any]
    shared: bool
