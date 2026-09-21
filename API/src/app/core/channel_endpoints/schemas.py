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

from pydantic import BaseModel, ConfigDict

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


__all__ = [
    "EndpointType",
    "EmailEndpointDetailsOut",
    "ChannelEndpointOut",
    "ChannelEndpointListOut",
    "DeactivateEndpointIn",
]
