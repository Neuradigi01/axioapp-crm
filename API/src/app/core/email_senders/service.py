"""Business logic for the per-org SMTP sender-identity module.

Five entry points:

  * :func:`create_smtp_sender` — encrypt the supplied SMTP password
    with Fernet, mint a 6-digit verification code, insert the row,
    then dispatch the code TO the ``from_address`` VIA the supplied
    SMTP creds. Tests connectivity in the same call: SMTP failure ⇒
    the row is deleted + a 400 is raised carrying the SMTP error.
  * :func:`verify_smtp_sender` — check the sha256 of the submitted
    code against the stored hash + expiry. On success stamps
    ``verified_at`` and, when this is the org's first verified
    sender, auto-flips ``is_default=True``.
  * :func:`resend_code` — regenerate + redispatch the 6-digit code.
  * :func:`list_unified_senders` — merges verified SMTP senders +
    live OAuth mailboxes into one list for the frontend.
  * :func:`set_default_sender` / :func:`delete_sender` — obvious.

Only this file holds transactions. The DAL never commits/flushes;
the router only calls this service.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.models import EmailAccount, EmailAccountSyncState
from src.app.core.email_senders import data_access
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.email_senders.schemas import (
    SmtpSenderCreate,
    UnifiedSenderOut,
)
from src.utilities.fernet_util import fernet

logger = logging.getLogger(__name__)

_VERIFICATION_TTL = timedelta(minutes=30)


# --- helpers ---------------------------------------------------------


def _generate_code() -> str:
    """Zero-padded 6-digit numeric code — matches the app's OTP shape."""
    return f"{secrets.randbelow(1_000_000):06d}"


# mailgun-inbound track: opaque per-sender token that becomes the local
# part of the outbound Reply-To address (``in_<token>@<INBOUND_EMAIL_DOMAIN>``).
# 12 chars of URL-safe base64 = ~60 bits of entropy post-slice. Matches
# the migration-side backfill helper (0215). UNIQUE-collision at these
# odds is <1e-18 per sender — on that vanishingly rare event the DB
# constraint raises and the caller retries.
_INBOUND_TOKEN_LEN = 12


def _generate_inbound_token() -> str:
    """12-char URL-safe token. Used as the local-part of the sender's
    ``in_<token>@<INBOUND_EMAIL_DOMAIN>`` Reply-To address."""
    return secrets.token_urlsafe(9)[: _INBOUND_TOKEN_LEN]


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _format_from(row: EmailSmtpSender) -> str:
    """``"Display Name <addr>"`` or bare ``addr`` depending on the row."""
    if row.display_name:
        return f"{row.display_name} <{row.from_address}>"
    return row.from_address


async def _send_via_smtp(
    row: EmailSmtpSender,
    *,
    subject: str,
    body_text: str,
    to_email: str,
    password: str | None = None,
) -> None:
    """Ship one plain-text message using the row's SMTP creds.

    ``password`` overrides the row's stored (encrypted) password so
    :func:`create_smtp_sender` can send the verification code with
    the raw plaintext the caller submitted, before the row has been
    persisted with a decryptable ciphertext round-trip.

    Raises :class:`aiosmtplib.SMTPException` (or one of its
    subclasses) on any failure — caller decides how to surface it.
    """
    if password is None:
        password = fernet.decrypt(row.smtp_password_enc)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _format_from(row)
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    use_tls = row.tls_mode == "tls"
    start_tls = row.tls_mode == "starttls"

    tls_context: ssl.SSLContext | None = None
    if use_tls or start_tls:
        tls_context = ssl.create_default_context()

    smtp = aiosmtplib.SMTP(
        hostname=row.smtp_host,
        port=row.smtp_port,
        use_tls=use_tls,
        start_tls=False,  # we drive STARTTLS explicitly below
        tls_context=tls_context,
        timeout=20.0,
    )
    await smtp.connect()
    try:
        if start_tls:
            await smtp.starttls(tls_context=tls_context)
        await smtp.login(row.smtp_username, password)
        await smtp.send_message(msg)
    finally:
        try:
            await smtp.quit()
        except Exception:  # pragma: no cover — best-effort shutdown
            pass


# --- write paths ----------------------------------------------------


async def create_smtp_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: SmtpSenderCreate,
) -> EmailSmtpSender:
    """Insert a pending SMTP sender + email the verification code.

    Fails fast (400) with the SMTP error message when the creds can't
    connect / auth / send — the row is torn down before the exception
    propagates so a broken submit never leaves a dead placeholder.
    """
    from_address = payload.from_address.lower()
    existing = await data_access.find_by_org_and_from(
        session, org_id=org_id, from_address=from_address
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An SMTP sender for '{from_address}' already exists.",
        )

    code = _generate_code()
    now = datetime.now(UTC)
    raw_password = payload.smtp_password.get_secret_value()

    row = EmailSmtpSender(
        org_id=org_id,
        from_address=from_address,
        display_name=payload.display_name,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password_enc=fernet.encrypt(raw_password),
        tls_mode=payload.tls_mode,
        inbound_token=_generate_inbound_token(),
        verification_code_hash=_hash_code(code),
        verification_expires_at=now + _VERIFICATION_TTL,
    )
    data_access.add_sender(session, row)
    # ``inbound_token`` UNIQUE conflict on ~60-bit collision would raise
    # here; the caller retries the request and gets a fresh token.
    # A retry loop in-process would need to rollback + rebuild the row,
    # which tears down the outer transaction unnecessarily for a
    # <1e-18 per-sender event.
    await session.flush()  # allocate row.id + expose UNIQUE conflicts

    subject = "Verify your CRM sender identity"
    body = (
        f"Your verification code is {code}. Enter it in the CRM to activate this sender identity."
    )

    try:
        await _send_via_smtp(
            row,
            subject=subject,
            body_text=body,
            to_email=row.from_address,
            password=raw_password,
        )
    except Exception as exc:
        # Roll back the placeholder row so a broken submit doesn't
        # leave an un-verifiable stub behind.
        await session.rollback()
        logger.warning(
            "email_senders.create_smtp_sender smtp_failed org=%s from=%s error=%s",
            org_id,
            from_address,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SMTP verification send failed: {exc}",
        ) from exc

    await session.commit()
    await session.refresh(row)
    return row


async def verify_smtp_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_id: uuid.UUID,
    code: str,
) -> EmailSmtpSender:
    """Confirm the 6-digit code and flip the row to verified.

    Auto-flips ``is_default=True`` when this is the first verified
    sender for the org so ``resolve_org_sender`` has something to
    return without a second click.
    """
    row = await data_access.get_by_id(session, org_id=org_id, sender_id=sender_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SMTP sender not found.",
        )
    if row.verified_at is not None:
        # Idempotent — re-verifying an already-verified row is a no-op.
        return row
    if row.verification_code_hash is None or row.verification_expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code pending. Request a new one.",
        )
    if datetime.now(UTC) > row.verification_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code expired. Request a new one.",
        )
    if _hash_code(code) != row.verification_code_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect verification code.",
        )

    # Check verified-count BEFORE mutating the row so autoflush can't
    # include this row and skew "first verified sender wins default".
    verified_count_before = await data_access.count_verified(session, org_id=org_id)
    data_access.mark_verified(row, when=datetime.now(UTC))
    if verified_count_before == 0:
        await data_access.clear_all_defaults(session, org_id=org_id)
        data_access.set_default(row)

    await session.commit()
    await session.refresh(row)
    return row


async def resend_code(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_id: uuid.UUID,
) -> EmailSmtpSender:
    """Mint a fresh 6-digit code + email it. 400 if the row is
    already verified — nothing to send."""
    row = await data_access.get_by_id(session, org_id=org_id, sender_id=sender_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SMTP sender not found.",
        )
    if row.verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This sender is already verified.",
        )

    code = _generate_code()
    now = datetime.now(UTC)
    row.verification_code_hash = _hash_code(code)
    row.verification_expires_at = now + _VERIFICATION_TTL

    subject = "Verify your CRM sender identity"
    body = (
        f"Your verification code is {code}. Enter it in the CRM to activate this sender identity."
    )
    try:
        await _send_via_smtp(
            row,
            subject=subject,
            body_text=body,
            to_email=row.from_address,
        )
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "email_senders.resend_code smtp_failed org=%s sender=%s error=%s",
            org_id,
            sender_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SMTP verification send failed: {exc}",
        ) from exc

    await session.commit()
    await session.refresh(row)
    return row


async def set_default_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_id: uuid.UUID,
) -> EmailSmtpSender:
    """Mark one SMTP sender as the org's default; unset any prior
    default. Only verified rows can hold the default flag."""
    row = await data_access.get_by_id(session, org_id=org_id, sender_id=sender_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SMTP sender not found.",
        )
    if row.verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verify the sender before making it default.",
        )
    await data_access.clear_all_defaults(session, org_id=org_id)
    data_access.set_default(row)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_id: uuid.UUID,
) -> None:
    """Remove one SMTP sender. 404 on miss, idempotent on repeat."""
    deleted = await data_access.delete_by_id(session, org_id=org_id, sender_id=sender_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SMTP sender not found.",
        )
    await session.commit()


# --- reads ----------------------------------------------------------


async def list_unified_senders(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[UnifiedSenderOut]:
    """Merge verified SMTP senders + live OAuth mailboxes into one
    list. Sort SMTP first, then Gmail, then Microsoft (matches the
    frontend Integrations card's provider-grouping expectation)."""
    smtp_rows = await data_access.list_smtp_senders(session, org_id=org_id)
    oauth_result = await session.execute(
        select(EmailAccount)
        .where(EmailAccount.org_id == org_id)
        .order_by(EmailAccount.connected_at.asc())
    )
    oauth_rows = list(oauth_result.scalars().all())

    merged: list[UnifiedSenderOut] = []
    for r in smtp_rows:
        merged.append(
            UnifiedSenderOut(
                kind="smtp",
                id=str(r.id),
                from_address=r.from_address,
                display_name=r.display_name,
                verified=r.verified_at is not None,
                is_default=r.is_default,
            )
        )
    for r in oauth_rows:
        provider = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
        if provider not in ("gmail", "microsoft"):
            continue
        # Hide disconnected rows from the sender list — the row is
        # retained in the DB so connect/disconnect history survives a
        # reconnect, but the operator has already told us they no
        # longer want to send from this identity. Surfacing it as
        # "Syncing…" (the pre-live fallback) misleads them into
        # thinking a re-sync is in flight when it isn't.
        if r.sync_state == EmailAccountSyncState.disconnected:
            continue
        # `verified` here means "the outbound resolver will pick this
        # up right now" — must stay in lockstep with the OAuth branch
        # of `shared.email.org_sender.resolve_org_sender`. Both
        # deliberately DON'T require sync_state='live': the inbound
        # 30-day backfill is orthogonal to send readiness. Requiring
        # 'live' meant every workflow email waited on that backfill
        # + stayed silently broken forever when the backfill task got
        # killed mid-run.
        sendable = r.refresh_token_enc is not None
        sync_state_value = (
            r.sync_state.value if hasattr(r.sync_state, "value") else str(r.sync_state)
        )
        merged.append(
            UnifiedSenderOut(
                kind=provider,  # type: ignore[arg-type]
                id=str(r.id),
                from_address=r.email_address,
                display_name=r.display_name,
                verified=sendable,
                # OAuth mailboxes don't carry a default flag today —
                # the resolver falls through to them only when no
                # verified SMTP sender exists.
                is_default=False,
                # Health fields — the frontend card uses these to
                # render a countdown + a red "reconnect required"
                # banner. `token_expires_at` is the short-lived
                # access-token deadline (refreshes in place unless
                # the grant was revoked); `last_sync_error` +
                # `sync_state == 'error'` are the "grant is dead"
                # signals.
                token_expires_at=r.token_expires_at,
                sync_state=sync_state_value,
                last_sync_error=r.last_sync_error,
            )
        )

    def _sort_key(row: UnifiedSenderOut) -> tuple[int, str]:
        order = {"smtp": 0, "gmail": 1, "microsoft": 2}
        return order[row.kind], row.from_address.lower()

    merged.sort(key=_sort_key)
    return merged


__all__ = [
    "create_smtp_sender",
    "delete_sender",
    "list_unified_senders",
    "resend_code",
    "set_default_sender",
    "verify_smtp_sender",
]
