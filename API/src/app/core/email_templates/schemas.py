"""Pydantic v2 schemas for the email-templates API.

Public projection (`EmailTemplateRead`) preserves all fields a Step
10 editor needs to round-trip a template without a second fetch:
`variables_used` carries the set the editor's sidebar renders.

Render request/response (`EmailTemplateRender*`) carries the inputs
needed to materialise a preview from a saved template.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel


class EmailTemplateCreate(BaseModel):
    """Request body for `POST /api/v1/email/templates`.

    `body_text` is optional — when omitted, the server derives a
    plain-text version from `body_html` on save. `is_active` defaults
    to true.
    """

    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=998)
    body_html: str = Field(min_length=1)
    body_text: Optional[str] = Field(default=None)
    is_active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True)


class EmailTemplateUpdate(BaseModel):
    """Partial update for `PATCH /api/v1/email/templates/{id}`.

    Every field is optional; absent fields stay unchanged. Re-running
    save-time validation (variable allowlist + Jinja-statement
    rejection) happens on any change to subject / body_html.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    subject: Optional[str] = Field(
        default=None, min_length=1, max_length=998
    )
    body_html: Optional[str] = Field(default=None, min_length=1)
    body_text: Optional[str] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class EmailTemplateRead(ORMModel):
    """Public projection."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    subject: str
    body_html: str
    body_text: str
    variables_used: list[str]
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class EmailTemplateListResponse(BaseModel):
    """Paginated list — page/size/total + items."""

    items: list[EmailTemplateRead]
    total: int
    page: int
    size: int


class EmailTemplateRenderResponse(BaseModel):
    """`POST /api/v1/email/templates/{id}/render` response shape.

    Returns the substituted subject + bodies — exactly the payload
    Step 5's `send_email` would emit if the template were sent now.
    `variables_used` echoes the template's saved list so the editor
    can keep showing the sidebar without a second fetch.
    """

    subject: str
    body_html: str
    body_text: str
    variables_used: list[str]


class VariableRegistryEntry(BaseModel):
    """One row in `GET /api/v1/email/templates/variables` — Step 10's
    editor sidebar consumes this list. Each entry is a fully-qualified
    dot-path with a human label.
    """

    path: str
    label: str
    category: str
    source: str  # "system" | "custom"


__all__ = [
    "EmailTemplateCreate",
    "EmailTemplateListResponse",
    "EmailTemplateRead",
    "EmailTemplateRenderResponse",
    "EmailTemplateUpdate",
    "VariableRegistryEntry",
]
