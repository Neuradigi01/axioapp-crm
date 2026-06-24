"""Pydantic v2 schemas for the campaigns module."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from src.app.core.campaigns.models import CampaignMessageStatus, CampaignStatus
from src.app.core.conversations.models import ConversationChannel
from src.app.shared.schemas import ORMModel, PaginatedResponse


class AudienceFilter(BaseModel):
    """Campaign audience target — three mutually-exclusive modes:

      1. **Empty** (`{}`): "Everyone in the org". The default.
      2. **Filter**: any of `q` / `source` / `tag` — same shape as the
         `/contacts` list query. Dynamic resolution at send time.
      3. **Group**: `group_id` references a saved `contact_groups` row
         (Step 3.5.7). Dynamic groups re-resolve at send time; static
         groups send to their frozen member list.

    Mixing modes 2 and 3 is rejected at the schema layer — the
    audience builder UI (Step 3.5.9) enforces "one mode at a time"
    via radio toggle, and the backend echoes the same constraint so
    a direct API call can't bypass it."""

    q: Optional[str] = None
    source: Optional[str] = None
    tag: Optional[str] = None
    group_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _no_mixed_modes(self) -> "AudienceFilter":
        has_filter = bool(self.q or self.source or self.tag)
        has_group = self.group_id is not None
        if has_filter and has_group:
            raise ValueError(
                "Use either filter fields (q/source/tag) OR group_id, not both."
            )
        return self


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
    # whatsapp-platform-upgrade Step 27b — multi-number per org.
    # NULL falls back to the org default phone; an explicit value
    # pins the dispatcher to that Meta phone-number-id.
    send_from_phone_id: Optional[str] = Field(default=None, max_length=64)
    # whatsapp-platform-upgrade Step 29 — A/B testing knobs. When
    # ``is_ab_test`` is True, the four other A/B fields drive the
    # split + winner decision. When False, every other A/B field
    # is ignored (and the underlying columns stay at server defaults).
    is_ab_test: bool = False
    variant_a_template_id: Optional[uuid.UUID] = None
    variant_b_template_id: Optional[uuid.UUID] = None
    split_ratio: int = Field(default=50, ge=0, le=100)
    winner_metric: Optional[
        Literal["reply_rate", "read_rate", "click_rate"]
    ] = None
    winner_holdback_hours: int = Field(default=24, ge=1, le=168)

    @model_validator(mode="after")
    def _exactly_one_template_source(self) -> "CampaignCreate":
        """Either free-text body or an approved-template reference —
        not both, not neither. Mixing the two would make dispatch's
        text-vs-template branch (Step 3.5.6) ambiguous.

        Step 29 — A/B campaigns skip this check because they pin
        templates via ``variant_a_template_id`` / ``variant_b_template_id``
        instead of ``template`` / ``template_id``."""
        if self.is_ab_test:
            return self
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

    @model_validator(mode="after")
    def _validate_ab_config(self) -> "CampaignCreate":
        """Step 29 — A/B campaigns must carry both template ids + a
        distinct pair + a winner metric. The minimum-audience guard
        is enforced at start-campaign time (we don't know the
        audience size until then)."""
        if not self.is_ab_test:
            return self
        if (
            self.variant_a_template_id is None
            or self.variant_b_template_id is None
        ):
            raise ValueError(
                "A/B campaigns require both variant_a_template_id "
                "and variant_b_template_id."
            )
        if self.variant_a_template_id == self.variant_b_template_id:
            raise ValueError(
                "Variant A and B must reference different templates."
            )
        if self.winner_metric is None:
            raise ValueError(
                "A/B campaigns require a winner_metric "
                "(reply_rate / read_rate / click_rate)."
            )
        return self


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    audience_filter: Optional[AudienceFilter] = None
    template: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    template_id: Optional[uuid.UUID] = None
    template_variables: Optional[dict[str, TemplateVariableBinding]] = None
    schedule_at: Optional[datetime] = None


class CampaignOut(ORMModel):

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


CampaignListResponse = PaginatedResponse[CampaignOut]


class CampaignMessageOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    channel_message_id: Optional[str]
    status: CampaignMessageStatus
    error: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
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
