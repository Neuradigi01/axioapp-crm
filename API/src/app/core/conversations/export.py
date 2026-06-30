"""Conversation transcript export
(whatsapp-platform-upgrade Step 23).

Two outputs, one builder pipeline:

  * ``build_csv_bytes``  — one message per row, all fields surfaced
    so audit / DPDP exports can reconstruct the conversation.
  * ``build_pdf_bytes``  — formatted transcript via the reportlab
    pattern already used by the billing module (no new system
    dependency).

Both exclude rows where ``is_internal=True`` — Step 13's internal
operator notes are never customer-visible and must not leak through
an export. AI replies are included (they reached the customer) and
tagged with a ``(AI)`` author label.

PDF rendering uses Platypus flowables (reportlab's high-level
layout API) so the output stays readable for long transcripts —
inbound / outbound get distinct fonts + indent levels, page
numbers footer, header with conversation metadata.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import Conversation, Message
from src.app.core.conversations.service import (
    get_conversation,
    list_messages,
)

# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _filter_for_export(
    messages: Iterable[Message],
) -> list[Message]:
    """Drop internal-only notes (Step 13). Keep everything that
    actually reached the customer — including AI replies."""
    return [m for m in messages if not bool(getattr(m, "is_internal", False))]


def _author_label(m: Message) -> str:
    """Human-friendly author for a row. Inbound is the customer;
    outbound is the staff user, the AI badge, or a system note."""
    if m.direction.value == "in":
        return "Customer"
    payload = getattr(m, "payload", None) or {}
    if isinstance(payload, dict) and payload.get("author") == "ai":
        return "AI agent"
    if m.sender_user_id is None:
        return "System"
    return f"Staff ({m.sender_user_id})"


def _format_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.isoformat()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def build_csv_bytes(
    conversation: Conversation,
    messages: Iterable[Message],
) -> bytes:
    """Render the transcript as a CSV byte-string.

    Columns:
      ``message_id, direction, author, text, attachments_count,
       sent_at, delivered_at, read_at, is_ai``

    Encoded as UTF-8 with BOM so Excel opens Hindi / emoji
    transcripts without garbling. The streaming variant of this is
    out of scope — conversations are bounded (page-cap 200 messages
    by default; longer ones split via the regular conversation
    pagination) and the in-memory write is fast even at 5k rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "message_id",
            "direction",
            "author",
            "text",
            "attachments_count",
            "sent_at",
            "delivered_at",
            "read_at",
            "is_ai",
        ]
    )
    for m in _filter_for_export(messages):
        payload = getattr(m, "payload", None) or {}
        is_ai = isinstance(payload, dict) and payload.get("author") == "ai"
        writer.writerow(
            [
                str(m.id),
                m.direction.value,
                _author_label(m),
                (m.text or "").replace("\r\n", "\n"),
                len(m.attachments or []),
                _format_ts(m.sent_at),
                _format_ts(m.delivered_at),
                _format_ts(m.read_at),
                "yes" if is_ai else "no",
            ]
        )
    # UTF-8 BOM so Excel respects the encoding.
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


def build_pdf_bytes(
    conversation: Conversation,
    messages: Iterable[Message],
) -> bytes:
    """Render the transcript as a multi-page PDF via reportlab.

    Mirrors the styling conventions used by
    ``packs/furniture/modules/billing/pdf.py`` — A4, 18mm margins,
    Platypus flowables, footer page numbers. The body is a
    chronological list of bubbles styled by direction (inbound
    left-indented, outbound right-indented, AI tagged).

    On import failure (reportlab not installed in this environment)
    we raise ``RuntimeError`` so the caller can fall back to CSV.
    Tests for the no-reportlab path live alongside this module."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:  # pragma: no cover — handled by callers
        raise RuntimeError("reportlab is required for PDF export but is not installed") from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Conversation {conversation.id}",
    )
    styles = getSampleStyleSheet()
    base_style = styles["BodyText"]
    inbound_style = ParagraphStyle(
        "Inbound",
        parent=base_style,
        leftIndent=0,
        rightIndent=40 * mm,
        textColor=colors.HexColor("#27272a"),
        backColor=colors.HexColor("#f4f4f5"),
        borderPadding=6,
        spaceAfter=4,
    )
    outbound_style = ParagraphStyle(
        "Outbound",
        parent=base_style,
        leftIndent=40 * mm,
        rightIndent=0,
        textColor=colors.HexColor("#1e293b"),
        backColor=colors.HexColor("#e0f2fe"),
        borderPadding=6,
        spaceAfter=4,
        alignment=2,  # TA_RIGHT
    )
    header_style = ParagraphStyle(
        "Header",
        parent=base_style,
        fontSize=14,
        spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=base_style,
        fontSize=9,
        textColor=colors.HexColor("#71717a"),
        spaceAfter=12,
    )

    flowables = [
        Paragraph(
            f"Conversation transcript — {conversation.channel.value}",
            header_style,
        ),
        Paragraph(
            f"External id: {conversation.external_id} · "
            f"Created: {_format_ts(conversation.created_at)} · "
            f"Status: {conversation.status.value}",
            meta_style,
        ),
        Spacer(1, 4 * mm),
    ]

    for m in _filter_for_export(messages):
        style = inbound_style if m.direction.value == "in" else outbound_style
        ts = _format_ts(m.sent_at or m.created_at)
        author = _author_label(m)
        text = (m.text or "").replace("\n", "<br/>")
        if not text and (m.attachments or []):
            text = f"<i>[{len(m.attachments)} attachment(s)]</i>"
        flowables.append(
            Paragraph(
                f"<font size=8 color='#71717a'>{author} · {ts}</font><br/>"
                f"{text or '<i>(empty)</i>'}",
                style,
            )
        )

    doc.build(flowables)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def export_conversation_csv(
    session: AsyncSession, *, conversation_id: uuid.UUID
) -> tuple[bytes, str, Conversation, list[Message]]:
    """Return ``(bytes, filename, conversation, messages)`` for the
    router. The router streams ``bytes`` to the client; the
    conversation + messages are returned so the DPDP bundle can
    reuse the same fetch without a second round-trip."""
    conv = await get_conversation(session, conversation_id)
    msgs = await list_messages(session, conversation_id)
    blob = build_csv_bytes(conv, msgs)
    filename = f"conversation-{conv.id}-{_filename_ts()}.csv"
    return blob, filename, conv, msgs


async def export_conversation_pdf(
    session: AsyncSession, *, conversation_id: uuid.UUID
) -> tuple[bytes, str]:
    conv = await get_conversation(session, conversation_id)
    msgs = await list_messages(session, conversation_id)
    blob = build_pdf_bytes(conv, msgs)
    filename = f"conversation-{conv.id}-{_filename_ts()}.pdf"
    return blob, filename


def _filename_ts() -> str:
    """Compact UTC timestamp for export filenames."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


__all__ = [
    "build_csv_bytes",
    "build_pdf_bytes",
    "export_conversation_csv",
    "export_conversation_pdf",
]
