"""Celery tasks for the Mailgun inbound module.

Step 4 fills the ingest task body. Flow:

  1. Read the pending-inbound directory the webhook wrote in Step 3.
  2. Extract the recipient token → resolve sender → org.
  3. Set the RLS tenant context inside the Celery worker.
  4. Guard: reject payloads whose ``To/Cc`` names >1 of our tokens.
  5. Parse Mailgun's SPF/DKIM verdicts.
  6. Match the sender email → contact.
  7. Apply the spoof policy: SPF-fail OR DKIM-fail AND a contact
     matched → drop the auto-attribution + skip workflow events
     (Attacker C2 CEO-fraud fix).
  8. Detect auto-responder headers → skip workflow events.
  9. Call the shared ``_persist_inbound_email`` helper (with the
     ``mg:<mailgun_delivery_id>`` channel_message_id — Mailgun's
     minted id, NOT the RFC ``Message-ID`` the sender chose; Attacker
     M3 fix).
 10. Clean up the pending directory on success. On exhausted retries
     Celery's ``on_failure`` fires ``_write_to_dlq`` and the directory
     stays in place for the admin reprocess flow (Step 5).

Attachments: Step 4 passes ``attachments=[]``. Step 5 wires the
staging-to-messages/ two-phase attachment write into this same task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.app.core import audit
from src.app.core.channel_endpoints import data_access as endpoints_da
from src.app.core.contacts import data_access as contacts_da
from src.app.core.conversations.adapters.email import _persist_inbound_email
from src.app.core.conversations.adapters.email_threading import (
    extract_message_id,
    extract_thread_keys,
)
from src.app.core.email.mailgun import data_access as mailgun_da
from src.app.core.email.mailgun import service as mailgun_service
from src.app.core.email_senders import data_access as senders_da
from src.app.shared.db import async_session
from src.celery.worker import celery


def _endpoints_refactor_enabled() -> bool:
    """Feature flag for the ``tasks/email-endpoint-abstraction`` Track 1 refactor.

    Default ``true`` in prod. Setting ``EMAIL_ENDPOINTS_REFACTOR_ENABLED=false``
    restores the pre-Step-3 legacy path (``senders_da.find_by_inbound_token``)
    unchanged — a one-flip revert for the refactor without touching migrations.
    Rip the flag out once Tracks 2/4/5 all consume the endpoints DAL.
    """
    return (
        os.getenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "true").strip().lower()
        != "false"
    )

logger = logging.getLogger(__name__)


@celery.task(
    name="src.app.core.email.mailgun.tasks.process_mailgun_inbound",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def process_mailgun_inbound(self, pending_path: str) -> None:
    """Ingest one Mailgun-delivered inbound email.

    Runs synchronous around ``asyncio.run(_process_async(...))`` so
    the Celery prefork model gets a fresh event loop per task —
    matches the ``core.email.tasks`` pattern (see
    ``_reset_db_engine_per_task`` in ``celery/worker.py``).
    """
    try:
        asyncio.run(_process_async(self, Path(pending_path)))
    except Exception:
        # If this was the LAST retry, fall through to on_failure below.
        # Otherwise let autoretry_for re-raise.
        if self.request.retries >= (self.max_retries or 0):
            asyncio.run(
                _write_to_dlq(
                    Path(pending_path),
                    reason="worker_exhausted",
                    detail={"retries": self.request.retries},
                )
            )
            # Swallow — DLQ row is the durable record now.
            return
        raise


async def _process_async(task, pending_dir: Path) -> None:
    if not pending_dir.exists():
        logger.info(
            "mailgun.ingest: pending path %s missing — likely already processed",
            pending_dir,
        )
        return

    payload_file = pending_dir / "payload.json"
    if not payload_file.exists():
        await _write_to_dlq(
            pending_dir,
            reason="missing_payload_json",
            detail={"path": str(pending_dir)},
        )
        return

    try:
        payload: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))
    except Exception as exc:
        await _write_to_dlq(
            pending_dir,
            reason="payload_json_parse_error",
            detail={"error": str(exc)},
        )
        return

    mailgun_delivery_id = (
        payload.get("Message-Id")
        or payload.get("message-id")
        or payload.get("message-headers-message-id")
        or ""
    ).strip()
    if not mailgun_delivery_id:
        await _write_to_dlq(
            pending_dir,
            reason="missing_mailgun_delivery_id",
            detail={"payload_keys": sorted(payload.keys())},
        )
        return

    # Multi-recipient guard: reject deliveries that resolve to more
    # than one of our inbound tokens. Rare (would mean Mailgun's Route
    # matched two of our recipients in one delivery), ambiguous, and
    # safer to drop than route to one arbitrarily.
    our_recipients = mailgun_service.extract_all_our_recipients(payload)
    if len(our_recipients) > 1:
        await audit.log(
            "mailgun.inbound.multi_recipient",
            entity_type="webhook_attempt",
            after={
                "recipients": our_recipients,
                "mailgun_delivery_id": mailgun_delivery_id,
            },
            org_id=None,
        )
        _cleanup(pending_dir)
        return

    recipient = our_recipients[0] if our_recipients else str(
        payload.get("recipient", "")
    )
    token = mailgun_service.extract_recipient_token(recipient)
    if not token:
        await audit.log(
            "mailgun.inbound.unknown_recipient",
            entity_type="webhook_attempt",
            after={
                "recipient": recipient,
                "reason": "malformed_recipient",
                "mailgun_delivery_id": mailgun_delivery_id,
            },
            org_id=None,
        )
        _cleanup(pending_dir)
        return

    async with async_session() as session:
        # Track 1 Step 3 refactor: consult ``channel_endpoints`` DAL first
        # when the flag is on; legacy ``senders_da.find_by_inbound_token``
        # is preserved behind ``EMAIL_ENDPOINTS_REFACTOR_ENABLED=false``.
        # Both paths yield the same ``sender`` value + the same drop
        # semantics on missing/inactive/deleted rows — the endpoint join
        # in ``find_by_reply_token`` filters ``is_active=True`` and the
        # details FK cascades on SMTP-sender deletion, so a stale endpoint
        # row cannot resolve to a live sender.
        endpoint = None
        if _endpoints_refactor_enabled():
            hit = await endpoints_da.find_by_reply_token(session, token=token)
            if hit is not None:
                endpoint, details = hit
                sender = await senders_da.get_by_id(
                    session,
                    org_id=endpoint.org_id,
                    sender_id=details.smtp_sender_id,
                )
            else:
                sender = None
        else:
            sender = await senders_da.find_by_inbound_token(session, token)
        if sender is None:
            # Unknown token — sender row was deleted, or the token
            # was rotated. System-level audit only (never surface to
            # any tenant — leaking sender emails across orgs would
            # be a PII bug).
            await audit.log(
                "mailgun.inbound.unknown_recipient",
                entity_type="webhook_attempt",
                after={
                    "recipient": recipient,
                    "reason": "no_sender_for_token",
                    "mailgun_delivery_id": mailgun_delivery_id,
                },
                org_id=None,
            )
            _cleanup(pending_dir)
            return

        org_id = sender.org_id

        # Set the RLS tenant context inside the Celery worker session —
        # every ORM read/write below runs scoped to this org.
        # ``SET LOCAL`` doesn't accept parametric binds (asyncpg
        # translates to ``$1`` which Postgres rejects on GUC-set
        # statements). Use ``set_config(name, value, is_local=TRUE)``
        # which is the SQL-native equivalent + accepts binds cleanly.
        await session.execute(
            text("SELECT set_config('app.current_org_id', :o, TRUE)"),
            {"o": str(org_id)},
        )

        # Parse SPF/DKIM verdicts + auto-responder headers.
        headers = mailgun_service.extract_headers(payload)
        spf_result = mailgun_service.parse_spf_result(payload)
        dkim_result = mailgun_service.parse_dkim_result(payload)
        auto_generated = mailgun_service.detect_auto_responder(headers)

        # Contact match (organic).
        sender_email = mailgun_service.parse_sender_email(payload)
        contact = None
        if sender_email:
            contact = await contacts_da.find_contact_by_email(
                session, org_id=org_id, email=sender_email
            )
        contact_id = contact.id if contact else None

        # Sender-auth spoof policy: if either SPF or DKIM explicitly
        # failed AND a contact matched, DROP the auto-attribution +
        # flag the message + skip workflow events (Attacker C2). A
        # ``fail`` verdict is stricter than a ``softfail``; only
        # ``fail`` triggers the drop so upstream mailers with
        # occasional softfails (very common) don't lose replies.
        spoof_suspected = False
        if contact_id is not None and (
            spf_result == "fail" or dkim_result == "fail"
        ):
            spoof_suspected = True
            contact_id = None
            await audit.log(
                "mailgun.inbound.sender_auth_failed",
                entity_type="contact",
                entity_id=contact.id if contact else None,
                after={
                    "sender_email": sender_email,
                    "spf": spf_result,
                    "dkim": dkim_result,
                    "mailgun_delivery_id": mailgun_delivery_id,
                },
                org_id=org_id,
            )

        # Also NULL contact + no workflow when we couldn't match.
        if contact_id is None and not spoof_suspected:
            await audit.log(
                "mailgun.inbound.no_contact_match",
                entity_type="webhook_attempt",
                after={
                    "sender_email": sender_email,
                    "mailgun_delivery_id": mailgun_delivery_id,
                },
                org_id=org_id,
            )

        publish_events = not (spoof_suspected or auto_generated)

        # Threading keys (In-Reply-To, References). Uses the same
        # extractor the OAuth path uses.
        thread_keys = extract_thread_keys(headers)
        # RFC Message-ID from headers is preserved in payload for
        # threading only — NOT used as the idempotency key.
        rfc_message_id = extract_message_id(headers)

        # Body text — Mailgun ships plain text + stripped/quoted
        # variants. Prefer stripped-text (reply chain stripped) as
        # the "text" of the message, matching Gmail sync's preference
        # for readable prose. Fall back to body-plain ONLY when
        # stripped-text is absent from the payload — an *empty*
        # stripped-text (reply with only an attachment / only a
        # signature) is a valid Mailgun verdict of "no new prose to
        # display" and must NOT be overridden with the quoted body,
        # otherwise every attachment-only reply renders as the full
        # quoted thread in the CRM inbox.
        if "stripped-text" in payload:
            body_text = str(payload.get("stripped-text") or "").strip()
        else:
            body_text = str(payload.get("body-plain") or "").strip()
        if "stripped-html" in payload:
            body_html = payload.get("stripped-html") or None
        else:
            body_html = payload.get("body-html") or None

        # Extract attachments into ``./storage/{org_id}/staging/
        # {request_id}/`` FIRST (Attacker M5: two-phase write). The
        # request_id is the pending-inbound directory's UUID name.
        try:
            request_id = uuid.UUID(pending_dir.name)
        except ValueError:
            # Odd directory name (recovery / manual re-enqueue) —
            # fabricate a fresh UUID so staging can happen safely.
            request_id = uuid.uuid4()

        attachments_meta, stripped_reason = mailgun_service.extract_and_stage_attachments(
            pending_dir, org_id=org_id, request_id=request_id
        )

        source_reference: dict[str, Any] = {
            "smtp_sender_id": str(sender.id),
            "mailgun_delivery_id": mailgun_delivery_id,
            "rfc_message_id": rfc_message_id,
            "spoof_suspected": spoof_suspected,
            "system_review_required": (
                spoof_suspected or contact_id is None
                or sender.verified_at is None
            ),
        }
        # Track 1 Step 3: stamp the resolved endpoint id when the new
        # DAL was consulted. Absent under the legacy flag path so old
        # rows persisted before the flip stay indistinguishable from
        # legacy-path rows — the ONE allowed shape difference between
        # the two paths (byte-identical DB output otherwise).
        if endpoint is not None:
            source_reference["endpoint_id"] = str(endpoint.id)
        if stripped_reason is not None:
            source_reference["attachment_stripped_reason"] = stripped_reason

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
            provider_message_id=None,  # Mailgun path doesn't use the fallback dedup
            provider_message_id_fallback_provider=None,
            spf_result=spf_result,
            dkim_result=dkim_result,
            auto_generated=auto_generated,
            source_provider="mailgun",
            source_reference=source_reference,
            publish_workflow_events=publish_events,
            # No user attribution for Mailgun inbound — the CRM didn't
            # perform an action; the customer sent us mail.
            activity_user_id=None,
            account_email_label=sender.from_address,
        )
        if message is None:
            logger.info(
                "mailgun.ingest: dedupe hit for delivery=%s (already persisted)",
                mailgun_delivery_id,
            )
        elif attachments_meta:
            # ONLY after the Message row commits do we move staged
            # attachments into ``messages/{message_id}/``.
            mailgun_service.commit_attachments(
                org_id=org_id,
                request_id=request_id,
                message_id=message.id,
            )

    _cleanup(pending_dir)


def _cleanup(pending_dir: Path) -> None:
    """Remove the on-disk pending-inbound directory after a
    successful (or intentionally-dropped) delivery."""
    try:
        shutil.rmtree(pending_dir)
    except FileNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover — filesystem edge
        logger.warning(
            "mailgun.ingest: failed to remove pending dir %s: %s",
            pending_dir,
            exc,
        )


async def _write_to_dlq(
    pending_dir: Path, *, reason: str, detail: dict[str, Any] | None = None
) -> None:
    """Persist a DLQ row for a delivery whose ingest failed terminally.

    Leaves the on-disk directory in place so the admin reprocess flow
    (Step 5) can re-enqueue against the original payload.
    """
    try:
        async with async_session() as session:
            mailgun_da.insert_dlq_row(
                session,
                # org_id is not resolved for most failure reasons; when
                # it is (rare), the caller could pass it via a future
                # signature extension. For Step 4 we accept NULL org.
                org_id=None,
                mailgun_delivery_id=None,
                pending_inbound_path=str(pending_dir),
                error_reason=reason[:64],
                error_details=detail,
                retry_count=0,
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover — DB down at DLQ write
        logger.error(
            "mailgun.ingest: DLQ write failed for %s (reason=%s): %s",
            pending_dir,
            reason,
            exc,
        )


__all__ = ["process_mailgun_inbound"]
