"""Forwarded-address ingest branch — ``f-<token>@<inbound>``.

Step 3 of ``tasks/email-inbound-forwarding/``.

The Mailgun ingest Celery task in
:mod:`src.app.core.email.mailgun.tasks` dispatches by local-part
prefix — ``in_*`` routes to the shipped reply-capture flow (in the
task file itself), ``f-*`` routes to :func:`handle_forwarded_address`
in this module.

Why factor this out (vs inline like reply-capture)?

The forwarded-address branch is meaningfully different from
reply-capture:

  * Token maps to a :class:`ChannelEndpoint` (endpoint-first), not to
    an SMTP-sender row (sender-first).
  * Sender is an **unknown third party** contacting our customer's
    support address, not a known contact replying to our outbound —
    so the "no contact match" path is the primary flow, not the edge.
  * Newly-created conversations need to route to the endpoint's
    ``default_assignee_user_id`` (an inbox-triage feature reply-
    capture doesn't have).

Keeping this in its own module means the reply-capture tasks.py
stays legible and the two flows don't accidentally share behaviour
via a giant if/else spaghetti.

Auto-create-contact is DEFERRED to Step 4 — this Step 3 leaves
``contact_id=None`` when no match, with an audit event that Step 4's
implementation reads to decide whether to auto-create.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.channel_endpoints import data_access as endpoints_da
from src.app.core.contacts import data_access as contacts_da
from src.app.core.conversations.adapters.email import _persist_inbound_email
from src.app.core.conversations.adapters.email_threading import (
    extract_message_id,
    extract_thread_keys,
)
from src.app.core.conversations.models import Conversation
from src.app.core.email.mailgun import service as mailgun_service

logger = logging.getLogger(__name__)


ENDPOINT_TYPE = "forwarded_address"


async def handle_forwarded_address(
    session: AsyncSession,
    *,
    token: str,
    recipient: str,
    payload: dict[str, Any],
    pending_dir: Path,
    mailgun_delivery_id: str,
) -> bool:
    """Process one ``f-<token>@<inbound>`` inbound delivery.

    Returns True when a Message row was persisted (or the delivery
    was a dedupe hit that mapped to an existing row). Returns False
    when the delivery was audit-dropped — the caller cleans up the
    on-disk pending directory in both cases; the boolean is for the
    caller's log/metrics only.

    Assumes the caller has already:
      * verified the recipient shape (``f-<token>``) via
        :func:`mailgun_service.parse_recipient_kind`.
      * confirmed there's exactly one of our recipients in the
        delivery (multi-recipient guard is upstream).

    Applies the shipped Mailgun-inbound policy verbatim: SPF/DKIM
    fail + a matched contact → drop the auto-attribution + flag
    spoof-suspected + skip workflow events; auto-submitted headers
    → skip workflow events.
    """
    # ------------------------------------------------------------------
    # Endpoint lookup (org resolution)
    # ------------------------------------------------------------------
    hit = await endpoints_da.find_by_forwarding_token(session, token=token)
    if hit is None:
        # ``find_by_forwarding_token`` filters ``is_active=True`` — a
        # missing hit means the token is unknown OR the endpoint was
        # deactivated. Either way, drop with an audit that surfaces
        # the recipient (never the token) for operator triage.
        await audit.log(
            "mailgun.inbound.forwarded_unknown_token",
            entity_type="webhook_attempt",
            after={
                "recipient": recipient,
                "reason": "no_endpoint_for_token_or_inactive",
                "mailgun_delivery_id": mailgun_delivery_id,
            },
            org_id=None,
        )
        return False

    endpoint, details = hit
    org_id = endpoint.org_id

    # ------------------------------------------------------------------
    # RLS tenant context — every ORM read/write below is org-scoped.
    # ``SET LOCAL`` doesn't accept parametric binds; use ``set_config``
    # (matches the reply-capture path's exact pattern).
    # ------------------------------------------------------------------
    await session.execute(
        sql_text("SELECT set_config('app.current_org_id', :o, TRUE)"),
        {"o": str(org_id)},
    )

    # ------------------------------------------------------------------
    # Header parsing + sender-auth verdicts.
    # ------------------------------------------------------------------
    headers = mailgun_service.extract_headers(payload)
    spf_result = mailgun_service.parse_spf_result(payload)
    dkim_result = mailgun_service.parse_dkim_result(payload)
    auto_generated = mailgun_service.detect_auto_responder(headers)

    sender_email = mailgun_service.parse_sender_email(payload)
    contact = None
    if sender_email:
        contact = await contacts_da.find_contact_by_email(
            session, org_id=org_id, email=sender_email
        )
    contact_id = contact.id if contact else None
    system_review_required = False

    # ------------------------------------------------------------------
    # Sender-auth spoof policy — mirrors reply-capture's Attacker C2 fix.
    # ------------------------------------------------------------------
    spoof_suspected = False
    if contact_id is not None and (spf_result == "fail" or dkim_result == "fail"):
        spoof_suspected = True
        contact_id = None
        system_review_required = True
        await audit.log(
            "mailgun.inbound.sender_auth_failed",
            entity_type="contact",
            entity_id=contact.id if contact else None,
            after={
                "sender_email": sender_email,
                "spf": spf_result,
                "dkim": dkim_result,
                "mailgun_delivery_id": mailgun_delivery_id,
                "endpoint_type": ENDPOINT_TYPE,
            },
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # Auto-create-contact policy for unmatched senders.
    # ------------------------------------------------------------------
    if contact_id is None and not spoof_suspected:
        if details.auto_create_contact:
            # Auto-create from the RFC ``From:`` header. Idempotent
            # (returns the existing contact on a re-fire). Errors
            # fail-soft: an unparseable header drops the auto-attribution
            # and persists the message with ``contact_id=None`` so the
            # data isn't lost.
            from src.app.core.contacts.service import (
                InvalidFromHeader,
                auto_create_from_email,
            )

            from_header = headers.get("from") or headers.get("From") or ""
            try:
                new_contact = await auto_create_from_email(
                    session,
                    org_id=org_id,
                    from_header=from_header,
                    source="email_forwarded_address",
                )
                contact_id = new_contact.id
            except InvalidFromHeader:
                system_review_required = True
                await audit.log(
                    "mailgun.inbound.forwarded_invalid_from_header",
                    entity_type="webhook_attempt",
                    after={
                        "from_header": from_header,
                        "endpoint_id": str(endpoint.id),
                        "mailgun_delivery_id": mailgun_delivery_id,
                    },
                    org_id=org_id,
                )
            except Exception:
                # Belt-and-braces: any other error inside auto-create
                # must never take down the ingest. Log + persist
                # message with contact_id=None + flag for review.
                system_review_required = True
                logger.exception(
                    "mailgun.forwarded_ingest.auto_create_failed org=%s from=%s delivery=%s",
                    org_id,
                    from_header,
                    mailgun_delivery_id,
                )
        else:
            system_review_required = True
            await audit.log(
                "mailgun.inbound.forwarded_no_contact_match",
                entity_type="webhook_attempt",
                after={
                    "sender_email": sender_email,
                    "endpoint_id": str(endpoint.id),
                    "mailgun_delivery_id": mailgun_delivery_id,
                    "auto_create_disabled": True,
                },
                org_id=org_id,
            )

    publish_events = not (spoof_suspected or auto_generated)

    # ------------------------------------------------------------------
    # Threading + body extraction (same shape as reply-capture path).
    # ------------------------------------------------------------------
    thread_keys = extract_thread_keys(headers)
    rfc_message_id = extract_message_id(headers)

    if "stripped-text" in payload:
        body_text = str(payload.get("stripped-text") or "").strip()
    else:
        body_text = str(payload.get("body-plain") or "").strip()
    if "stripped-html" in payload:
        body_html = payload.get("stripped-html") or None
    else:
        body_html = payload.get("body-html") or None

    # Attachments — same two-phase staging pattern as the reply-capture
    # path. ``request_id`` re-uses the pending-directory name so
    # commit_attachments can locate the staging dir on success.
    try:
        request_id = uuid.UUID(pending_dir.name)
    except ValueError:
        request_id = uuid.uuid4()

    attachments_meta, stripped_reason = mailgun_service.extract_and_stage_attachments(
        pending_dir, org_id=org_id, request_id=request_id
    )

    source_reference: dict[str, Any] = {
        "endpoint_id": str(endpoint.id),
        "endpoint_type": ENDPOINT_TYPE,
        "forwarding_token": token,
        "mailgun_delivery_id": mailgun_delivery_id,
        "rfc_message_id": rfc_message_id,
        "spoof_suspected": spoof_suspected,
        "system_review_required": system_review_required,
    }
    if stripped_reason is not None:
        source_reference["attachment_stripped_reason"] = stripped_reason

    # ------------------------------------------------------------------
    # Persist the inbound message via the shared helper. Handles
    # threading (existing conversation via In-Reply-To / References /
    # contact-latest) and creates a fresh conversation on first-touch.
    # ------------------------------------------------------------------
    message = await _persist_inbound_email(
        session,
        org_id=org_id,
        contact_id=contact_id,
        headers=headers,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments_meta,
        channel_message_id=f"mg:{mailgun_delivery_id}",
        thread_keys=thread_keys,
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result=spf_result,
        dkim_result=dkim_result,
        auto_generated=auto_generated,
        source_provider="mailgun",
        source_reference=source_reference,
        publish_workflow_events=publish_events,
        activity_user_id=None,
        account_email_label=None,
        endpoint_id=endpoint.id,
        endpoint_type=ENDPOINT_TYPE,
    )

    # ------------------------------------------------------------------
    # Post-hoc: apply the endpoint's default_assignee to a FRESH
    # conversation. When the message threaded onto an existing
    # conversation, we leave the current assignee alone (the
    # operator may already be triaging it).
    # ------------------------------------------------------------------
    if message is not None and details.default_assignee_user_id is not None:
        conv = await session.get(Conversation, message.conversation_id)
        if conv is not None and conv.assigned_to_id is None:
            conv.assigned_to_id = details.default_assignee_user_id
            await session.commit()

    # ------------------------------------------------------------------
    # Successful ingest → stamp ``last_inbound_at`` on the details row
    # + commit staged attachments into their final directory.
    # ------------------------------------------------------------------
    if message is not None:
        from datetime import UTC, datetime

        details.last_inbound_at = datetime.now(UTC)
        await session.commit()
        if attachments_meta:
            await mailgun_service.commit_attachments(
                org_id=org_id,
                request_id=request_id,
                message_id=message.id,
            )
        return True

    # Dedupe hit — Message row was already persisted for this
    # ``mg:<delivery_id>``. Caller cleans up the pending dir.
    return True


__all__ = ["ENDPOINT_TYPE", "handle_forwarded_address"]
