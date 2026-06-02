"""Pydantic v2 schemas for the contact-groups API surface.

`GroupFilter` mirrors the existing `AudienceFilter` shape from
`campaigns.schemas` — kept locally to avoid an import cycle with
campaigns (groups are referenced BY campaigns, not the other way).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.shared.schemas import PaginatedResponse


class GroupFilter(BaseModel):
    """Filter predicates for a dynamic group — same `q/source/tag`
    shape as the `/contacts` query. Custom-field filters added in a
    future step; the JSON column accepts forward-compatible extras
    via `extra='allow'`."""

    model_config = ConfigDict(extra="allow")

    q: Optional[str] = None
    source: Optional[str] = None
    tag: Optional[str] = None


class GroupCreate(BaseModel):
    """Body for `POST /api/v1/contact-groups`.

    For dynamic groups, set `is_dynamic=true` + `filter_json`.
    For static groups, set `is_dynamic=false` + `contact_ids`.
    Validator enforces mutual exclusivity so a malformed payload
    fails at the API surface rather than in the DB."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_dynamic: bool = False
    filter_json: Optional[GroupFilter] = None
    contact_ids: Optional[list[uuid.UUID]] = Field(
        default=None,
        description="Required for static groups; ignored for dynamic.",
    )

    @model_validator(mode="after")
    def _check_mode_consistency(self) -> "GroupCreate":
        if self.is_dynamic:
            if self.filter_json is None:
                raise ValueError(
                    "Dynamic groups require `filter_json`."
                )
            if self.contact_ids:
                raise ValueError(
                    "Dynamic groups must not include `contact_ids`; "
                    "use `filter_json` only."
                )
        else:
            if self.contact_ids is None:
                raise ValueError(
                    "Static groups require `contact_ids` (use empty "
                    "list `[]` for a zero-member group)."
                )
            if self.filter_json is not None:
                raise ValueError(
                    "Static groups must not include `filter_json`; "
                    "use `contact_ids` only."
                )
        return self


class GroupUpdate(BaseModel):
    """Partial update — name/description always editable; member set
    or filter replaceable depending on mode.

    Switching modes (static ↔ dynamic) is NOT supported via update —
    delete + recreate is the explicit path. Keeps the logic small
    and the audit trail clean."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    filter_json: Optional[GroupFilter] = None
    contact_ids: Optional[list[uuid.UUID]] = None


class GroupRead(BaseModel):
    """List + read projection. `member_count` is computed by the
    service (cheap COUNT for static; filter-eval COUNT for dynamic)
    so the UI can show "82 contacts" without a second round-trip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    is_dynamic: bool
    filter_json: Optional[dict[str, Any]] = None
    created_by_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    member_count: Optional[int] = None


class GroupDetail(GroupRead):
    """Detail view — adds a sample of member ids (first 10) for the
    edit-page preview. Full member list lives behind a separate
    paginated endpoint if we ever need it."""

    sample_contact_ids: list[uuid.UUID] = Field(default_factory=list)


GroupListResponse = PaginatedResponse[GroupRead]


class PreviewSizeIn(BaseModel):
    """Body for `POST /api/v1/contact-groups/preview-size`.

    Exactly one of `filter_json` or `group_id` must be set — the
    campaign audience builder (Step 3.5.9) calls this with either
    a freshly-typed filter (before saving as a group) or a saved
    group's id (to show "X contacts will receive this")."""

    model_config = ConfigDict(extra="forbid")

    filter_json: Optional[GroupFilter] = None
    group_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "PreviewSizeIn":
        if (self.filter_json is None) == (self.group_id is None):
            raise ValueError(
                "Provide exactly one of `filter_json` or `group_id`."
            )
        return self


class PreviewSizeOut(BaseModel):
    count: int


__all__ = [
    "GroupCreate",
    "GroupDetail",
    "GroupFilter",
    "GroupListResponse",
    "GroupRead",
    "GroupUpdate",
    "PreviewSizeIn",
    "PreviewSizeOut",
]
