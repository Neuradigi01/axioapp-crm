"""Pydantic v2 schemas for the campaigns module."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.campaigns.models import CampaignMessageStatus, CampaignStatus
from src.app.core.conversations.models import ConversationChannel


class AudienceFilter(BaseModel):
    """Same shape as `/contacts` list query — q / source / tag."""

    q: Optional[str] = None
    source: Optional[str] = None
    tag: Optional[str] = None


class TemplateVariableBinding(BaseModel):
    """One `{{n}} → value` binding inside `template_variables`.

    `kind='static'`: `value` is the literal text every recipient sees.
    `kind='field'`:  `value` is a contact-field reference like
                     `full_name`, `phone`, `email`, `custom_data.<key>`.
                     Step 3.5.6 dispatch resolves it per contact.
    """

    kind: Literal["static", "field"]
    value: str = Field(min_length=1, max_length=512)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel: ConversationChannel
    audience_filter: AudienceFilter = Field(default_factory=AudienceFilter)
    template: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    template_id: Optional[uuid.UUID] = None
    template_variables: Optional[dict[str, TemplateVariableBinding]] = None
    schedule_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _exactly_one_template_source(self) -> "CampaignCreate":
        """Either free-text body or an approved-template reference —
        not both, not neither. Mixing the two would make dispatch's
        text-vs-template branch (Step 3.5.6) ambiguous."""
        if self.template is None and self.template_id is None:
            raise ValueError(
                "Provide either 'template' (free text) or 'template_id' "
                "(approved Meta template)."
            )
        if self.template is not None and self.template_id is not None:
            raise ValueError(
                "Use 'template' OR 'template_id', not both."
            )
        if self.template_id is not None and self.template_variables is None:
            # No variables for a 0-variable template is fine, but make
            # the field explicitly `{}` so dispatch doesn't see None.
            self.template_variables = {}
        return self


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    audience_filter: Optional[AudienceFilter] = None
    template: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    template_id: Optional[uuid.UUID] = None
    template_variables: Optional[dict[str, TemplateVariableBinding]] = None
    schedule_at: Optional[datetime] = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    channel: ConversationChannel
    audience_filter: dict[str, Any]
    template: Optional[str]
    template_id: Optional[uuid.UUID]
    template_variables: Optional[dict[str, Any]]
    schedule_at: Optional[datetime]
    status: CampaignStatus
    created_by_id: Optional[uuid.UUID]
    created_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignOut]
    total: int
    page: int
    size: int


class CampaignMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    channel_message_id: Optional[str]
    status: CampaignMessageStatus
    error: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime


class CampaignStatsOut(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    queued: int
    sent: int
    delivered: int
    read: int
    failed: int


class CampaignStartResponse(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    chunks_enqueued: int
    scheduled_at: Optional[datetime]
