"""Pydantic schemas for the automation engine.

Wire shapes for ``tbl_automation_triggers`` + ``tbl_automation_runs``.
Step 1 lands the basic Create / Update / Read shapes; the trigger
router (Step 3) consumes them. Conditions + recipient_resolver_config
stay loose ``dict`` types — Step 2 introduces a typed grammar for
each, but at the router boundary we accept any JSON-shaped object
and validate semantics in the service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.automation.models import AutomationRunStatus
from src.app.core.conversations.models import ConversationChannel


class TriggerCreate(BaseModel):
    """``POST /api/v1/automation/triggers`` body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=200)
    channel: ConversationChannel
    template_id: uuid.UUID
    enabled: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    delay_seconds: int = Field(default=0, ge=0, le=60 * 60 * 24 * 30)
    recipient_resolver: str = Field(default="contact.email", max_length=200)
    recipient_resolver_config: dict[str, Any] = Field(default_factory=dict)


class TriggerUpdate(BaseModel):
    """``PATCH /api/v1/automation/triggers/{id}`` body.

    Every field optional — operator can flip just ``enabled`` without
    re-supplying name / channel / template_id."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    event_type: str | None = Field(default=None, min_length=1, max_length=200)
    channel: ConversationChannel | None = None
    template_id: uuid.UUID | None = None
    enabled: bool | None = None
    conditions: dict[str, Any] | None = None
    delay_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 24 * 30)
    recipient_resolver: str | None = Field(default=None, max_length=200)
    recipient_resolver_config: dict[str, Any] | None = None


class TriggerRead(BaseModel):
    """Wire shape for ``GET /api/v1/automation/triggers/{id}`` +
    list responses."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    event_type: str
    channel: ConversationChannel
    template_id: uuid.UUID
    enabled: bool
    conditions: dict[str, Any]
    delay_seconds: int
    recipient_resolver: str
    recipient_resolver_config: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    updated_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RunRead(BaseModel):
    """Wire shape for the run-history endpoint (Step 9 UI consumes it)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    trigger_id: uuid.UUID
    event_id: str
    event_payload: dict[str, Any]
    contact_id: uuid.UUID | None
    user_id: uuid.UUID | None
    status: AutomationRunStatus
    channel_message_id: str | None
    error: str | None
    scheduled_at: datetime
    dispatched_at: datetime | None
    completed_at: datetime | None


# --- tasks/automation-conditions/ Step 2 ----------------------------


class FieldValuesRequest(BaseModel):
    """``POST /automations/event-types/{event}/field-values`` body.

    ``field`` is the dot-path the customer just picked in the
    condition builder's field dropdown (e.g. ``"lead.pipeline_stage"``).
    Must match one of the event's ``condition_fields`` entries — the
    service raises :class:`FieldNotFound` otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)


class EnumOptionOut(BaseModel):
    """One row in the value-dropdown response. Matches
    :class:`core.automation.enum_resolvers.EnumOption` on the wire."""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
