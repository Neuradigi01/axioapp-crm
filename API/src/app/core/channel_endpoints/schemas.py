"""Pydantic schemas for the ``/api/v1/channel-endpoints`` surface.

Response schemas only in Step 2. Create-endpoint schemas for the
concrete endpoint types (``forwarded_address``, ``oauth_mailbox``)
land with their respective tracks (Track 3, Track 2).

Deliberately excluded fields on ``EmailEndpointDetailsOut``:

* ``forwarding_token`` — opaque secret used at Mailgun's routing
  layer. Frontends surface it composed into the customer-facing
  address (``f-<token>@in.<domain>``) — never the raw token.

* ``reply_token`` — same. Composed into ``in_<token>@<domain>``
  by the mailgun-inbound module before render.

Field exclusion is enforced by the ``__pydantic_fields__``
declarations here — mass-assign of these fields on the response side
is impossible because they simply are not modelled.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas.base import ORMModel

EndpointType = Literal[
    "smtp_reply_capture",
    "oauth_mailbox",
    "forwarded_address",
    "custom_domain_inbound",
    "platform_reply_capture",
]


class EmailEndpointDetailsOut(ORMModel):
    """Email-specific detail block for an endpoint.

    Tokens deliberately absent (see module docstring). The two FK
    columns to concrete providers are exposed so the frontend can
    render "which SMTP sender / OAuth account this endpoint belongs
    to" without a second query.
    """

    endpoint_id: uuid.UUID
    domain_id: uuid.UUID | None = None
    smtp_sender_id: uuid.UUID | None = None
    oauth_account_id: uuid.UUID | None = None
    last_inbound_at: datetime | None = None
    # tasks/email-inbound-forwarding Step 2 — forwarded-address config.
    # Both columns exist on every row (server-defaulted); surfaced here
    # so a mixed list of endpoints renders the two forwarded-address
    # fields per row without a separate call.
    auto_create_contact: bool = True
    default_assignee_user_id: uuid.UUID | None = None


class ChannelEndpointOut(ORMModel):
    """One row of ``GET /api/v1/channel-endpoints``.

    ``details`` is populated in the service layer by a companion DAL
    fetch — the router flattens both into this response so callers
    don't chase a second endpoint.
    """

    id: uuid.UUID
    org_id: uuid.UUID
    channel: str
    endpoint_type: EndpointType
    label: str
    is_active: bool
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    details: EmailEndpointDetailsOut | None = None


class ChannelEndpointListOut(BaseModel):
    """Envelope around the list. Explicit envelope keeps room for
    future top-level fields (pagination cursor, active-count summary)
    without breaking clients that unwrap ``items``."""

    model_config = ConfigDict(extra="forbid")

    items: list[ChannelEndpointOut]


class DeactivateEndpointIn(BaseModel):
    """Optional reason string on ``POST /channel-endpoints/{id}/deactivate``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str | None = None


# ---------------------------------------------------------------------------
# tasks/email-inbound-forwarding Step 2 — forwarded-address create + read.
#
# The ``forwarding_token`` never appears on any response schema —
# frontends see only the composed address (``f-<token>@<domain>``).
# Enforced by omitting the field here; mass-assign on the request side
# is blocked by ``extra="forbid"`` + the field not existing on any
# request model.
# ---------------------------------------------------------------------------


class CreateForwardedAddressIn(BaseModel):
    """Payload for ``POST /api/v1/channel-endpoints/forwarded-address``.

    ``label`` is the operator-facing name for the endpoint (rendered
    in the inbox-settings list). ``auto_create_contact`` defaults to
    the industry-baseline "auto-create" (matches HubSpot / Front). A
    ``default_assignee_user_id`` of None means round-robin at inbox-
    triage time.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=128)
    auto_create_contact: bool = True
    default_assignee_user_id: uuid.UUID | None = None


class AssigneeRef(BaseModel):
    """Minimal user reference embedded in :class:`ForwardedAddressOut`.

    Only what the inbox-settings UI needs — a full user response would
    leak profile fields the settings-page doesn't render. Populated by
    the service layer via a join against ``tbl_user_info``.
    """

    id: uuid.UUID
    name: str


class ForwardedAddressOut(ORMModel):
    """Response shape for a ``forwarded_address`` endpoint.

    ``forwarding_address`` is composed server-side from
    ``INBOUND_EMAIL_DOMAIN`` + the raw ``forwarding_token`` — the raw
    token is NEVER surfaced to the client. Copy-paste flows show the
    full ``f-<token>@<domain>`` address; the token itself stays
    internal.
    """

    id: uuid.UUID
    label: str
    forwarding_address: str
    auto_create_contact: bool
    default_assignee: AssigneeRef | None = None
    is_active: bool
    last_inbound_at: datetime | None = None
    created_at: datetime


class TestInboundStatusOut(BaseModel):
    """Response for ``GET /channel-endpoints/{id}/test-inbound-status``.

    ``status='waiting'`` while no message has landed at this endpoint
    (``last_inbound_at`` is NULL). ``status='received'`` as soon as
    the first inbound bumps ``last_inbound_at``. The wizard uses this
    to flip its Step-3 badge from "Waiting for test" to "Received!".
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["waiting", "received"]
    last_inbound_at: datetime | None = None


class UpdateForwardedAddressIn(BaseModel):
    """Partial-update payload for a ``forwarded_address`` endpoint.

    Every field optional so the inbox-settings row-inline toggles can
    PATCH one attribute without re-sending the whole endpoint. Server
    treats missing fields as "unchanged" (Pydantic ``model_dump(exclude_unset=True)``
    in the service layer). ``default_assignee_user_id`` accepts NULL
    to clear the assignee back to round-robin.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str | None = Field(default=None, min_length=1, max_length=128)
    auto_create_contact: bool | None = None
    default_assignee_user_id: uuid.UUID | None = None


__all__ = [
    "AssigneeRef",
    "ChannelEndpointListOut",
    "ChannelEndpointOut",
    "CreateForwardedAddressIn",
    "DeactivateEndpointIn",
    "EmailEndpointDetailsOut",
    "EndpointType",
    "ForwardedAddressOut",
    "TestInboundStatusOut",
    "UpdateForwardedAddressIn",
]
