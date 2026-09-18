"""HTTP endpoints for the ``/api/v1/email-senders`` surface.

Gated by ``email.accounts.manage`` (same key the OAuth email-accounts
router uses — the two surfaces both let a rep manage the outbound
identity their sends will originate from).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email_senders import service
from src.app.core.email_senders.schemas import (
    SenderCaptureToggle,
    SmtpSenderCreate,
    SmtpSenderOut,
    SmtpSenderVerify,
    UnifiedSenderOut,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/email-senders", tags=["Email Senders"])


def _to_out(row) -> SmtpSenderOut:
    """Build the response schema with the Mailgun reply-address block
    attached. Kept here (not in the service) so the ORM row stays
    clean and the transformation is close to the HTTP boundary."""
    out = SmtpSenderOut.model_validate(row)
    out.inbound_reply_address = service.build_inbound_reply_address(row)
    return out


@router.get("/", response_model=list[UnifiedSenderOut])
async def list_senders_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> list[UnifiedSenderOut]:
    """Merged list — verified SMTP senders + live OAuth mailboxes."""
    return await service.list_unified_senders(db, org_id=user.org_id)


@router.post(
    "/smtp",
    response_model=SmtpSenderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_smtp_sender_endpoint(
    payload: SmtpSenderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> SmtpSenderOut:
    """Register an SMTP sender. Ships the 6-digit verification code
    to ``from_address`` using the submitted creds — a failure here
    surfaces the SMTP error verbatim so the operator can diagnose
    port/auth issues without checking logs."""
    row = await service.create_smtp_sender(db, org_id=user.org_id, payload=payload)
    return _to_out(row)


@router.post("/smtp/{sender_id}/verify", response_model=SmtpSenderOut)
async def verify_smtp_sender_endpoint(
    sender_id: uuid.UUID,
    payload: SmtpSenderVerify,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> SmtpSenderOut:
    """Submit the 6-digit code delivered to ``from_address``."""
    row = await service.verify_smtp_sender(
        db, org_id=user.org_id, sender_id=sender_id, code=payload.code
    )
    return _to_out(row)


@router.post("/smtp/{sender_id}/resend-code", response_model=SmtpSenderOut)
async def resend_code_endpoint(
    sender_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> SmtpSenderOut:
    """Regenerate + redispatch the verification code."""
    row = await service.resend_code(db, org_id=user.org_id, sender_id=sender_id)
    return _to_out(row)


@router.post("/{sender_id}/set-default", status_code=status.HTTP_204_NO_CONTENT)
async def set_default_sender_endpoint(
    sender_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Mark this sender — SMTP or OAuth — as the org's default.

    Polymorphic: ``sender_id`` may point to a row in
    ``tbl_email_smtp_senders`` OR ``tbl_email_accounts``. The service
    resolves which table, validates sendability (verified SMTP OR
    connected OAuth), and atomically clears the flag on both tables
    before flipping the winner.

    Returns 204 rather than the row because the two return types
    would need a discriminated response schema for a single UI-only
    action; the frontend re-fetches the unified list after this
    fires anyway.
    """
    await service.set_default_sender(
        db, org_id=user.org_id, sender_id=sender_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/smtp/{sender_id}/capture-toggle", response_model=SmtpSenderOut)
async def set_capture_toggle_endpoint(
    sender_id: uuid.UUID,
    payload: SenderCaptureToggle,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> SmtpSenderOut:
    """mailgun-inbound track: per-sender opt-out of Reply-To rewriting.

    When ``capture=false``, outbound mail from this sender leaves the
    caller-supplied ``Reply-To`` (or none) alone — replies go back to
    the SMTP mailbox instead of the CRM. Defaults to ``true`` on new
    senders.
    """
    row = await service.set_capture_toggle(
        db, org_id=user.org_id, sender_id=sender_id, capture=payload.capture
    )
    return _to_out(row)


@router.delete("/{sender_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sender_endpoint(
    sender_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Delete an SMTP sender. OAuth mailbox deletion continues to
    live on ``DELETE /api/v1/email/accounts/{id}``."""
    await service.delete_sender(db, org_id=user.org_id, sender_id=sender_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
