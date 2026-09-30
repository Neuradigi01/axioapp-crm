"""Pure helpers for the conversations module (no DB access)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from fastapi import HTTPException, status

from src.app.core.conversations.models import Conversation, ConversationStatus

# Outbound email attachment limits. Gmail / Outlook reject messages over
# ~25 MB after base64 (+33%), so the raw total stays well under that.
MAX_EMAIL_ATTACHMENTS = 10
MAX_EMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_EMAIL_ATTACHMENTS_TOTAL_BYTES = 18 * 1024 * 1024

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True, slots=True)
class OutboundAttachment:
    """A file attached to an outbound email. ``filename`` is already
    sanitised to ``[A-Za-z0-9._-]`` and unique within the send (it doubles
    as the storage key the inbox downloads it by)."""

    filename: str
    content_type: str
    data: bytes


def wake_on_inbound(conversation: Conversation) -> None:
    """A customer message wakes a snoozed conversation back to ``open``.

    Snooze means "hide until the customer replies"; leaving the thread
    snoozed after they reply would bury the message outside the Open
    view. Closed conversations stay closed — reopening is an explicit
    operator action. Call on every inbound path before the commit.
    Any pending timed wake-up is cleared with it."""
    if conversation.status == ConversationStatus.snoozed:
        conversation.status = ConversationStatus.open
        conversation.snoozed_until = None


def prepare_email_attachments(
    files: list[tuple[str | None, str | None, bytes]],
) -> list[OutboundAttachment]:
    """Validate uploaded ``(filename, content_type, data)`` triples for an
    email reply and return send-ready attachments with safe, unique
    filenames. Raises 413 / 422 with an operator-readable message."""
    if len(files) > MAX_EMAIL_ATTACHMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Attach at most {MAX_EMAIL_ATTACHMENTS} files per email.",
        )
    out: list[OutboundAttachment] = []
    seen: dict[str, int] = {}
    total = 0
    for raw_name, content_type, data in files:
        if not data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"'{raw_name or 'attachment'}' is empty.",
            )
        if len(data) > MAX_EMAIL_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"'{raw_name or 'attachment'}' is larger than 10 MB.",
            )
        total += len(data)
        if total > MAX_EMAIL_ATTACHMENTS_TOTAL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Attachments exceed 18 MB in total — email providers would reject it.",
            )
        base_name = os.path.basename((raw_name or "").strip()) or "attachment.bin"
        safe = _UNSAFE_FILENAME_CHARS.sub("_", base_name)[:200] or "attachment.bin"
        count = seen.get(safe, 0) + 1
        seen[safe] = count
        if count > 1:
            stem, ext = os.path.splitext(safe)
            safe = f"{stem}-{count}{ext}"
        out.append(
            OutboundAttachment(
                filename=safe,
                content_type=(content_type or "application/octet-stream").lower(),
                data=data,
            )
        )
    return out
