"""Pydantic v2 schemas for the central template library.

Step 1 lands shapes only — no service / router consumes them yet
(Steps 2 + 3 do). The shapes mirror the SQLAlchemy models in
:mod:`core.templates.models` with channel-aware validation:
``subject`` + ``preview_text`` must be ``None`` for non-email
channels, and the email channel must carry a non-empty subject.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.shared.schemas.base import ORMModel


# ---- Request shapes ---------------------------------------------------


class TemplateCreate(BaseModel):
    """Payload for ``POST /api/v1/templates`` (Step 3).

    The variables list is NOT accepted from the client — Step 2's
    service parses ``body_text`` for ``{{var}}`` references and
    populates ``tbl_message_templates.variables`` itself. Clients
    that hand-author a list would otherwise drift from the body.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    channel: ConversationChannel
    category: TemplateCategory = TemplateCategory.marketing
    language: str = Field(default="en", min_length=2, max_length=16)
    body_text: str = Field(min_length=1, max_length=65535)
    subject: Optional[str] = Field(default=None, max_length=998)
    preview_text: Optional[str] = Field(default=None, max_length=190)

    @model_validator(mode="after")
    def _email_subject_required(self) -> "TemplateCreate":
        if self.channel == ConversationChannel.email:
            if not self.subject or not self.subject.strip():
                raise ValueError("subject is required for email templates")
        else:
            if self.subject is not None:
                raise ValueError(
                    f"subject is only valid for email templates; got channel={self.channel.value}"
                )
            if self.preview_text is not None:
                raise ValueError(
                    f"preview_text is only valid for email templates; got channel={self.channel.value}"
                )
        return self


class TemplateUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/templates/{id}`` (Step 3).

    All fields are optional — only those supplied are updated. The
    service enforces that channel cannot change after first save
    (different channels imply incompatible extension rows + variable
    sets). Subject/preview_text vs channel coherence is re-checked
    at the service layer against the persisted channel.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[TemplateCategory] = None
    language: Optional[str] = Field(default=None, min_length=2, max_length=16)
    body_text: Optional[str] = Field(default=None, min_length=1, max_length=65535)
    subject: Optional[str] = Field(default=None, max_length=998)
    preview_text: Optional[str] = Field(default=None, max_length=190)
    change_note: Optional[str] = Field(default=None, max_length=2000)


# ---- Read / response shapes ------------------------------------------


class TemplateRead(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    channel: ConversationChannel
    name: str
    category: TemplateCategory
    language: str
    body_text: str
    subject: Optional[str]
    preview_text: Optional[str]
    variables: list[Any]
    internal_status: TemplateInternalStatus
    external_status: TemplateExternalStatus
    external_provider_id: Optional[str]
    current_version: int
    created_by_user_id: Optional[uuid.UUID]
    updated_by_user_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class TemplateVersionRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    body_text: str
    subject: Optional[str]
    variables: list[Any]
    changed_by_user_id: Optional[uuid.UUID]
    changed_at: datetime
    change_note: Optional[str]


class TemplateReviewRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    reviewer_user_id: Optional[uuid.UUID]
    action: TemplateReviewAction
    note: Optional[str]
    created_at: datetime


class TemplateTestSendRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    channel: ConversationChannel
    sent_to: str
    sent_by_user_id: Optional[uuid.UUID]
    channel_message_id: Optional[str]
    sent_at: datetime


class WorkflowActionPayload(BaseModel):
    """Body for the five workflow-transition endpoints.

    ``note`` is mandatory for ``reject`` + ``request_changes`` —
    enforced at the workflow layer, not here, so a single Pydantic
    shape covers all five endpoints. The reject/request_changes
    handlers reject empty notes with 422.
    """

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    note: Optional[str] = None


class TestSendPayload(BaseModel):
    """Body for ``POST /api/v1/templates/{id}/test-send``.

    ``recipient`` is the channel-shaped address (email for email
    templates, phone E.164-without-plus for WhatsApp / SMS, channel
    handle for FB / IG / push). ``sample_context`` overlays the
    default sample data so the operator can preview how a specific
    contact's variables render before going live.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recipient: str = Field(min_length=1, max_length=255)
    sample_context: Optional[dict[str, Any]] = None
