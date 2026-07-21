"""DPDP right-to-access data export
(whatsapp-platform-upgrade Step 23).

Builds a ZIP archive containing **everything** the CRM stores about
a single contact — the legal contract DPDP-2023 §11 (a) puts on a
data fiduciary. Bundle shape::

    <contact-id>/
      manifest.json         — top-level metadata + index
      contact.json          — the contact row + opt-in state
      consent-events.json   — immutable consent log
      leads.json            — leads owned by this contact
      conversations.json    — per-conversation summary
      transcripts/
        <conversation-id>.csv
        <conversation-id>.pdf  (when reportlab is available)

JSON-first because it's machine-checkable; the per-conversation
PDFs are the human-readable companion the customer-service team
attaches to the email response. Everything UTF-8, every
timestamp ISO-8601, every UUID stringified.

The bundle never includes:
  * Other tenants' data (RLS-scoped session).
  * Internal notes (filtered by the transcript exporter).
  * Encryption keys, password hashes, anything from
    ``tbl_user_login`` / ``tbl_integrations`` etc.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.export import (
    build_csv_bytes,
    build_pdf_bytes,
)
from src.app.core.conversations.models import Conversation, Message
from src.app.core.conversations.service import list_messages

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DataExportBundle:
    contact_id: uuid.UUID
    archive_bytes: bytes
    filename: str
    summary: dict[str, Any]


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if hasattr(value, "value"):  # enum
        return value.value
    raise TypeError(f"unserialisable type: {type(value)}")


def _to_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        default=_json_default,
        sort_keys=True,
    ).encode("utf-8")


def _serialise_contact(contact: Any) -> dict[str, Any]:
    # DPDP right-to-access exports on an anonymised row surface the
    # placeholder full_name + null phone/email — flag the state
    # explicitly so an auditor / the data subject reading the archive
    # isn't misled into thinking the placeholder is real PII.
    anonymised_at = getattr(contact, "anonymised_at", None)
    return {
        "id": contact.id,
        "org_id": contact.org_id,
        "full_name": contact.full_name,
        "phone": contact.phone,
        "email": contact.email,
        "source": contact.source,
        "tags": list(contact.tags or []),
        # `notes` was retired from the contact row in migration 0158.
        # The DPDP export used to include this single-blob field; the
        # per-contact activity feed (which includes every note the
        # operator ever wrote about this contact) is exported through
        # the transcripts channel and remains the authoritative record.
        "custom_data": dict(contact.custom_data or {}),
        "assigned_to_id": contact.assigned_to_id,
        "last_activity_at": contact.last_activity_at,
        "email_opt_out": bool(getattr(contact, "email_opt_out", False)),
        "whatsapp_opt_in_status": getattr(contact, "whatsapp_opt_in_status", None),
        "whatsapp_opt_in_source": getattr(contact, "whatsapp_opt_in_source", None),
        "whatsapp_opt_in_recorded_at": getattr(contact, "whatsapp_opt_in_recorded_at", None),
        "whatsapp_opt_out_recorded_at": getattr(contact, "whatsapp_opt_out_recorded_at", None),
        "whatsapp_opt_out_reason": getattr(contact, "whatsapp_opt_out_reason", None),
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
        "anonymised": anonymised_at is not None,
        "anonymised_at": anonymised_at,
    }


def _serialise_consent_event(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "channel": event.channel,
        "old_status": event.old_status,
        "new_status": event.new_status,
        "source": event.source,
        "actor_user_id": event.actor_user_id,
        "ip_address": event.ip_address,
        "reason": event.reason,
        "request_evidence": dict(event.request_evidence or {}),
        "recorded_at": event.recorded_at,
    }


def _serialise_lead(lead: Any) -> dict[str, Any]:
    return {
        "id": lead.id,
        "status": getattr(lead, "status", None),
        "source": getattr(lead, "source", None),
        "estimated_value": getattr(lead, "estimated_value", None),
        "attribution": dict(getattr(lead, "attribution", None) or {}),
        "custom_data": dict(getattr(lead, "custom_data", None) or {}),
        "assigned_to_id": getattr(lead, "assigned_to_id", None),
        "created_at": getattr(lead, "created_at", None),
        "updated_at": getattr(lead, "updated_at", None),
    }


def _serialise_conversation(conv: Conversation, message_count: int) -> dict[str, Any]:
    return {
        "id": conv.id,
        "channel": conv.channel,
        "external_id": conv.external_id,
        "status": conv.status,
        "ai_handling": conv.ai_handling,
        "last_message_at": conv.last_message_at,
        "created_at": conv.created_at,
        "message_count": message_count,
    }


async def build_contact_data_export(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    requested_by_user_id: uuid.UUID | None,
) -> DataExportBundle:
    """Assemble the full DPDP bundle. Caller is responsible for
    auth + RLS (the SQLAlchemy ``after_begin`` hook is the gate;
    this function trusts the active tenant context)."""
    # Lazy imports — these modules have heavy transitive imports we
    # don't want at module-import time.
    from src.app.core.contacts.data_access import get_contact
    from src.app.core.contacts.models import ConsentEvent
    from src.app.core.leads.models import Lead

    contact = await get_contact(session, contact_id)
    if contact is None:
        raise LookupError(f"contact {contact_id} not found in this tenant")

    consent_rows = (
        (
            await session.execute(
                select(ConsentEvent)
                .where(ConsentEvent.contact_id == contact_id)
                .order_by(ConsentEvent.recorded_at.asc())
            )
        )
        .scalars()
        .all()
    )

    lead_rows = (
        (await session.execute(select(Lead).where(Lead.contact_id == contact_id))).scalars().all()
    )

    # Conversations linked to this contact. We hit the conversations
    # table directly (no service helper exists for "by contact_id")
    # — single tenant-scoped query.
    conversations = (
        (await session.execute(select(Conversation).where(Conversation.contact_id == contact_id)))
        .scalars()
        .all()
    )

    archive_buf = io.BytesIO()
    transcripts_summary: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        prefix = f"{contact_id}"

        zf.writestr(
            f"{prefix}/contact.json",
            _to_json_bytes(_serialise_contact(contact)),
        )
        zf.writestr(
            f"{prefix}/consent-events.json",
            _to_json_bytes([_serialise_consent_event(e) for e in consent_rows]),
        )
        zf.writestr(
            f"{prefix}/leads.json",
            _to_json_bytes([_serialise_lead(lead) for lead in lead_rows]),
        )

        conversation_meta: list[dict[str, Any]] = []
        for conv in conversations:
            msgs: list[Message] = await list_messages(session, conv.id)
            conversation_meta.append(_serialise_conversation(conv, message_count=len(msgs)))
            csv_bytes = build_csv_bytes(conv, msgs)
            zf.writestr(f"{prefix}/transcripts/{conv.id}.csv", csv_bytes)
            try:
                pdf_bytes = build_pdf_bytes(conv, msgs)
                zf.writestr(f"{prefix}/transcripts/{conv.id}.pdf", pdf_bytes)
                transcripts_summary.append(
                    {"conversation_id": str(conv.id), "formats": ["csv", "pdf"]}
                )
            except RuntimeError:
                # PDF dep missing — CSV still ships. Bundle stays
                # DPDP-compliant (text transcript present).
                transcripts_summary.append({"conversation_id": str(conv.id), "formats": ["csv"]})

        zf.writestr(
            f"{prefix}/conversations.json",
            _to_json_bytes(conversation_meta),
        )

        manifest = {
            "contact_id": str(contact_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "requested_by_user_id": (str(requested_by_user_id) if requested_by_user_id else None),
            "counts": {
                "consent_events": len(consent_rows),
                "leads": len(lead_rows),
                "conversations": len(conversations),
            },
            "transcripts": transcripts_summary,
            "schema_version": 1,
            "notes": (
                "DPDP right-to-access export. Internal operator notes "
                "(Step 13) are excluded from transcripts. Sensitive "
                "internal fields (auth, integration secrets) are "
                "never included."
            ),
        }
        zf.writestr(f"{prefix}/manifest.json", _to_json_bytes(manifest))

    # IST-anchored filename timestamp — matches the contacts CSV
    # export (`contacts/router.py::export_csv_endpoint`) so both
    # operator-facing artifacts follow the same convention. Mumbai
    # operator at 04:00 IST used to get a UTC-yesterday-dated ZIP
    # (`20260721T223000Z`) — misleading and search-unfriendly.
    IST = timezone(timedelta(hours=5, minutes=30))
    ist_now = datetime.now(UTC).astimezone(IST)
    timestamp = ist_now.strftime("%Y%m%dT%H%M%S")
    filename = f"contact-{contact_id}-data-export-{timestamp}-IST.zip"
    summary = {
        "contact_id": str(contact_id),
        "filename": filename,
        "conversations": len(conversations),
        "consent_events": len(consent_rows),
        "leads": len(lead_rows),
    }
    return DataExportBundle(
        contact_id=contact_id,
        archive_bytes=archive_buf.getvalue(),
        filename=filename,
        summary=summary,
    )


__all__ = ["DataExportBundle", "build_contact_data_export"]
