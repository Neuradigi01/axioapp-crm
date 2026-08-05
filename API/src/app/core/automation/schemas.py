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
from typing import Any, Literal

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


class MigratedWorkflowIdResponse(BaseModel):
    """Wire shape for ``GET /api/v1/automations/triggers/{id}/migrated-workflow-id``.

    Step-3 of ``tasks/workflows-absorb-automation/`` — the Angular
    redirect resolver reads this to know where to bounce a legacy
    ``/user/automations/{id}`` bookmark. ``workflow_id`` is the id of
    the single-step workflow the Step-1 migration created for this
    trigger; ``None`` when the trigger predates the migration or was
    created after (i.e. not part of the cutover). Never raises 404 —
    the endpoint returns ``{workflow_id: null}`` for missing triggers
    too, so the resolver can uniformly fall back to the workflows
    list.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: uuid.UUID | None = None


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


# --- tasks/automation-conditions/ Step 5 ----------------------------


class PreviewMatchesRequest(BaseModel):
    """``POST /automations/event-types/{event}/preview-matches`` body.

    Same AST shape the editor emits for ``TriggerCreate.conditions``.
    ``window_days`` bounds the historical scan — the editor's default
    is 7 (matches the copy under the sentence preview: "in the last
    7 days"). Max 30 days as a cheap DoS cap.
    """

    model_config = ConfigDict(extra="forbid")

    conditions: dict[str, Any] = Field(default_factory=dict)
    window_days: int = Field(default=7, ge=1, le=30)


class PreviewMatchesResponse(BaseModel):
    """Wire shape for the matched-events preview response.

    ``source`` distinguishes the honest "we scanned N runs" case
    from "we have no historical data for this event type" — the
    frontend renders a "no historical events available for preview"
    hint on ``'none'`` instead of a misleading zero-count. ``matched``
    + ``scanned`` are always populated (both zero for ``source='none'``).
    ``truncated=True`` when the scan hit the 500-row cap; the
    frontend renders "at least N" instead of the exact count.
    """

    model_config = ConfigDict(extra="forbid")

    matched: int
    scanned: int
    window_days: int
    source: Literal["runs", "none"]
    truncated: bool = False
