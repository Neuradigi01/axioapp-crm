"""Meta-mandated Data Deletion Callback service layer.

Meta requires every App that handles user data to expose a callback URL
that:

  1. Receives a form-encoded ``signed_request`` whenever a Meta user
     deletes our App from their Facebook profile.
  2. Validates the HMAC-SHA256 signature using the App Secret.
  3. Returns ``{url, confirmation_code}`` synchronously so the user can
     check the status later — Meta then re-fetches that URL when the
     user opens their privacy settings, sometimes months after the
     original deletion.

Reference: https://developers.facebook.com/docs/development/create-an-app
/app-dashboard/data-deletion-callback

This module owns ONLY the parsing + persistence half. The actual
anonymisation runs asynchronously in
``src.app.core.integrations.meta.tasks.delete_meta_user_data_async``
so the callback can return within Meta's expected sub-second window
regardless of how much data the affected orgs have accumulated.

Idempotency: Meta retries on transient failures, so the same
``(user_id, issued_at)`` pair may arrive multiple times within the
replay window. The endpoint collapses these by returning the existing
``confirmation_code`` rather than minting a new row — keeps the status
URLs Meta has already shown to users valid.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.meta.models import (
    MetaDataDeletionRequest,
    MetaDataDeletionStatus,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
)

logger = logging.getLogger(__name__)


# Meta enforces a ~10 min validity on the signed_request. Reject older
# payloads to prevent replay attacks where an attacker harvests one
# legitimate signature and replays it later. Meta itself never retries
# beyond this window.
_SIGNED_REQUEST_MAX_AGE_SECONDS = 10 * 60


# Confirmation codes are 64 url-safe characters (~384 bits of entropy).
# Acts as the capability key the public status page reads against —
# unguessable, so the status URL doesn't need user auth.
_CONFIRMATION_CODE_BYTES = 48


# Special demo confirmation code Meta reviewers can hit to confirm the
# status page renders correctly. NEVER associated with a real Meta
# user; lookups by this code return a synthetic "completed" projection
# without touching the DB.
DEMO_CONFIRMATION_CODE = "demo-test-12345"


# --- typed errors --------------------------------------------------------


class SignedRequestError(Exception):
    """Base class for signed_request validation failures.

    The endpoint surfaces each subclass as HTTP 400 with the same
    generic message ("invalid signed_request"). Specific reasons are
    logged server-side; revealing them in the response would help an
    attacker probe the validator (signature vs algorithm vs replay)."""


class InvalidSignatureError(SignedRequestError):
    """HMAC-SHA256 mismatch."""


class InvalidAlgorithmError(SignedRequestError):
    """Payload's ``algorithm`` field isn't ``HMAC-SHA256``."""


class StaleRequestError(SignedRequestError):
    """``issued_at`` is older than the replay window."""


class MalformedRequestError(SignedRequestError):
    """Payload could not be base64-decoded / JSON-parsed, or is missing
    a required field."""


# --- signed_request parser ----------------------------------------------


def parse_signed_request(
    signed_request: str,
    *,
    app_secret: str,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Verify Meta's signed_request and return the decoded payload.

    Format: ``<sig_b64>.<payload_b64>`` where both halves are
    url-safe-base64 with padding stripped. The signature is HMAC-SHA256
    of the raw payload bytes (the un-decoded base64 string per Meta's
    docs — NOT the JSON), keyed on the App Secret.

    Raises one of the typed exceptions above on failure. Callers wrap
    in HTTP 400 with a single generic message — don't leak the specific
    reason to the response body.
    """
    if not signed_request or "." not in signed_request:
        raise MalformedRequestError("missing signed_request payload")

    try:
        sig_b64, payload_b64 = signed_request.split(".", 1)
    except ValueError as exc:
        raise MalformedRequestError(f"split failed: {exc}") from exc

    try:
        sig = _b64_decode(sig_b64)
        payload_raw = _b64_decode(payload_b64)
    except (ValueError, base64.binascii.Error) as exc:
        raise MalformedRequestError(f"base64 decode failed: {exc}") from exc

    # Meta signs the BASE64-ENCODED payload string, not the decoded JSON
    # bytes. Match that exactly.
    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig, expected):
        raise InvalidSignatureError("HMAC mismatch")

    try:
        data = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise MalformedRequestError(f"json decode failed: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedRequestError("payload is not a JSON object")

    algorithm = data.get("algorithm")
    if algorithm != "HMAC-SHA256":
        raise InvalidAlgorithmError(
            f"unexpected algorithm: {algorithm!r}"
        )

    issued_at = data.get("issued_at")
    if not isinstance(issued_at, int):
        raise MalformedRequestError("issued_at missing or non-integer")
    current = now if now is not None else time.time()
    if current - issued_at > _SIGNED_REQUEST_MAX_AGE_SECONDS:
        raise StaleRequestError(
            f"signed_request too old: {current - issued_at:.0f}s"
        )

    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise MalformedRequestError("user_id missing")

    return data


def _b64_decode(value: str) -> bytes:
    """Url-safe base64 decode with automatic padding restoration. Meta
    strips trailing ``=`` per RFC 4648 §5; re-add it before decoding."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# --- persistence ---------------------------------------------------------


def generate_confirmation_code() -> str:
    """High-entropy URL-safe token. ~384 bits (48 bytes); truncated to
    64 chars after base64 to match the column length."""
    return secrets.token_urlsafe(_CONFIRMATION_CODE_BYTES)[:64]


async def find_existing_request(
    session: AsyncSession,
    *,
    meta_user_id: str,
    issued_at_epoch: int,
) -> Optional[MetaDataDeletionRequest]:
    """Idempotency check — Meta retries identical signed_requests on
    transient failures. Collapse them by reusing the existing row +
    its confirmation_code so the status URL Meta already showed the
    user keeps working."""
    issued_at_dt = datetime.fromtimestamp(issued_at_epoch, tz=timezone.utc)
    stmt = select(MetaDataDeletionRequest).where(
        MetaDataDeletionRequest.meta_user_id == meta_user_id,
        MetaDataDeletionRequest.issued_at == issued_at_dt,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_integrations_by_meta_user(
    session: AsyncSession, *, meta_user_id: str
) -> list[Integration]:
    """All Integration rows linked to this Meta identity, across all
    orgs. Bypasses the ORM tenant filter intentionally — the callback
    arrives without any tenant context (Meta doesn't send our JWT).
    Returns ``[]`` when the user never connected via ES (legacy
    manual-paste orgs have NULL ``meta_user_id`` and never match)."""
    from sqlalchemy import text as sql_text

    sql = sql_text(
        """
        SELECT id, org_id
        FROM tbl_integrations
        WHERE meta_user_id = :meta_user_id
          AND provider = :provider
        """
    )
    rows = (
        await session.execute(
            sql,
            {
                "meta_user_id": meta_user_id,
                "provider": IntegrationProvider.whatsapp.value,
            },
        )
    ).mappings().all()
    # Synthesise minimal Integration objects — the caller only reads
    # `.id` and `.org_id`. Avoids hydrating the full row + skirts the
    # auto-tenant-filter that would deny these reads.
    return [
        Integration(id=row["id"], org_id=row["org_id"])
        for row in rows
    ]


async def record_deletion_request(
    session: AsyncSession,
    *,
    meta_user_id: str,
    issued_at_epoch: int,
    affected_org_ids: list[uuid.UUID],
) -> MetaDataDeletionRequest:
    """Insert a ``pending`` row + return it. Caller is responsible for
    committing and kicking off the async deletion task."""
    row = MetaDataDeletionRequest(
        confirmation_code=generate_confirmation_code(),
        meta_user_id=meta_user_id,
        issued_at=datetime.fromtimestamp(issued_at_epoch, tz=timezone.utc),
        affected_org_ids=affected_org_ids,
        status=MetaDataDeletionStatus.pending,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_status_by_code(
    session: AsyncSession, *, confirmation_code: str
) -> Optional[dict[str, Any]]:
    """Public-facing status lookup. Returns a projection safe to render
    on an anonymous page — strips ``meta_user_id`` (PII) and the
    ``failure_reason`` internal detail.

    Special-cases the demo code so Meta reviewers can confirm the page
    renders even before any real deletion has occurred."""
    if confirmation_code == DEMO_CONFIRMATION_CODE:
        now = datetime.now(timezone.utc)
        return {
            "status": MetaDataDeletionStatus.completed.value,
            "confirmation_code": confirmation_code,
            "requested_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "affected_org_count": 1,
            "is_demo": True,
        }

    stmt = select(MetaDataDeletionRequest).where(
        MetaDataDeletionRequest.confirmation_code == confirmation_code
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return {
        "status": row.status.value,
        "confirmation_code": row.confirmation_code,
        "requested_at": row.requested_at.isoformat(),
        "completed_at": (
            row.completed_at.isoformat() if row.completed_at else None
        ),
        "affected_org_count": len(row.affected_org_ids or []),
        "is_demo": False,
    }


__all__ = [
    "DEMO_CONFIRMATION_CODE",
    "InvalidAlgorithmError",
    "InvalidSignatureError",
    "MalformedRequestError",
    "SignedRequestError",
    "StaleRequestError",
    "find_existing_request",
    "find_integrations_by_meta_user",
    "generate_confirmation_code",
    "get_status_by_code",
    "parse_signed_request",
    "record_deletion_request",
]
