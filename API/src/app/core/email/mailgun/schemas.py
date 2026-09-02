"""Pydantic schemas for the Mailgun inbound webhook.

The webhook itself doesn't consume a typed JSON body — Mailgun POSTs
``multipart/form-data`` with the field names its docs list. The
schemas here shape the *responses* we return to Mailgun.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WebhookAcceptedResponse(BaseModel):
    """200 OK body returned to Mailgun after a signed delivery has
    been persisted to disk + enqueued (or queued for the sweeper).

    Mailgun retries on any non-2xx; we return 200 the moment we've
    committed the payload to disk so a broker outage doesn't cause
    Mailgun to retry-storm. Ops observability lives in audit events
    + DLQ + the pending-inbound sweeper, not in the response body.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = "accepted"


class WebhookHealthResponse(BaseModel):
    """Health-check response for ``GET /webhooks/mailgun/inbound/health``.

    Used by Mailgun's URL validator + our own ops. No secrets — the
    domain is public (it's the receiving MX host anyway).
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    domain: str | None


class DlqRowOut(BaseModel):
    """DLQ inspection row for the admin endpoint.

    Deliberately does NOT expose ``pending_inbound_path`` (server-side
    filesystem path — no operator UI value + potential info leak) or
    the full ``error_details`` JSONB (may contain PII from spoofed
    inbound). ``error_reason`` + counts are enough for the operator
    to decide whether to reprocess.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    org_id: str | None
    mailgun_delivery_id: str | None
    error_reason: str
    retry_count: int
    created_at: str
    resolved_at: str | None


class DlqReprocessResponse(BaseModel):
    """Return shape for the reprocess endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str
    reprocessed: bool


__all__ = [
    "DlqReprocessResponse",
    "DlqRowOut",
    "WebhookAcceptedResponse",
    "WebhookHealthResponse",
]
