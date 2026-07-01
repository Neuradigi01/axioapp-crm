"""Service layer for per-user Google Calendar connections.

Per the manager's layered convention: only file that touches
transactions. Delegates row CRUD to :mod:`data_access` and OAuth
plumbing to :mod:`oauth`.

Four public entry points map 1:1 to the four router endpoints:

  * :func:`build_authorize_url` — assemble Google's consent URL for the
    calling user
  * :func:`complete_connection` — end-to-end callback: verify state,
    swap code for tokens, encrypt + persist the row
  * :func:`disconnect` — revoke upstream + delete the row
  * :func:`get_status` — read shape driving the integrations card
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.crypto import decrypt_optional, encrypt
from src.app.core.integrations.google_calendar import (
    data_access as _da,
    oauth as _oauth,
)
from src.app.core.integrations.google_calendar.models import GoogleCalendarToken


@dataclass(frozen=True, slots=True)
class CalendarConnectionStatus:
    """Shape the integrations card renders. ``connected=False`` for
    every other field being null."""

    connected: bool
    google_email: str | None
    last_error: str | None
    last_synced_at: datetime | None
    scopes_granted: list[str]


def build_authorize_url(*, org_id: uuid.UUID, user_id: int) -> str:
    """No DB writes — pure state-signing + URL construction. Wraps the
    OAuth-layer helper so the router only knows the service layer."""
    return _oauth.start_authorize(org_id=org_id, user_id=user_id)


async def complete_connection(
    session: AsyncSession,
    *,
    code: str,
    state: str,
) -> GoogleCalendarToken:
    """Callback endpoint's business logic:

    1. Verify state (HMAC signature + freshness) → extract the target
       ``(org_id, user_id)``. Google's browser hits the callback with
       no CRM Bearer token, so state HMAC + the 10-min TTL are the
       trust root. Google's returned ``code`` is single-use, so a
       state-replay attacker would also need to intercept the code
       from Google's response — the two together make the exchange
       infeasible.
    2. Exchange the auth code for tokens.
    3. Fetch userinfo → ``google_email`` + ``google_user_id``.
    4. Encrypt refresh + access tokens, upsert the row.

    Raises :class:`HTTPException` on any auth failure; the router
    converts to a redirect with an error param.
    """
    payload = _oauth.verify_state(state)
    state_user_id = payload.get("user_id")
    state_org_id_raw = payload.get("org_id")
    if not isinstance(state_user_id, int) or not state_org_id_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state missing user_id / org_id fields.",
        )
    try:
        state_org_id = uuid.UUID(state_org_id_raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state carries malformed org_id.",
        ) from None
    jwt_user_id = state_user_id
    jwt_org_id = state_org_id

    tokens = await _oauth.exchange_code_for_tokens(code)
    if tokens.refresh_token is None:
        # `prompt=consent` + `access_type=offline` should always force
        # Google to return a refresh_token. Missing = the user opened
        # a stale consent screen after we've already been granted; ask
        # them to try again (rare but possible).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google didn't return a refresh token. Disconnect at "
                "myaccount.google.com/permissions then reconnect."
            ),
        )
    try:
        userinfo = await _oauth.fetch_userinfo(tokens.access_token)
    except _oauth.GoogleCalendarOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google userinfo call failed: {exc}",
        ) from exc

    # Upsert — one row per (org_id, user_id). Overwrites on reconnect
    # so the new refresh token replaces the old one cleanly.
    existing = await _da.get_token_for_user(
        session, org_id=jwt_org_id, user_id=jwt_user_id
    )
    now = datetime.now(UTC)
    expires_at = datetime.fromtimestamp(tokens.expires_at, tz=UTC)
    if existing is None:
        row = GoogleCalendarToken(
            org_id=jwt_org_id,
            user_id=jwt_user_id,
            google_email=userinfo.email,
            google_user_id=userinfo.google_user_id,
            refresh_token_encrypted=encrypt(tokens.refresh_token),
            access_token_encrypted=encrypt(tokens.access_token),
            access_token_expires_at=expires_at,
            scopes_granted=list(tokens.scopes_granted),
            status="active",
            last_error=None,
            connected_at=now,
        )
        _da.add_token(session, row)
    else:
        # Update in place — never leave the operator with two rows.
        existing.google_email = userinfo.email
        existing.google_user_id = userinfo.google_user_id
        existing.refresh_token_encrypted = encrypt(tokens.refresh_token)
        existing.access_token_encrypted = encrypt(tokens.access_token)
        existing.access_token_expires_at = expires_at
        existing.scopes_granted = list(tokens.scopes_granted)
        existing.status = "active"
        existing.last_error = None
        existing.connected_at = now
        row = existing

    await session.flush()
    await session.commit()
    await session.refresh(row)
    return row


async def disconnect(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> bool:
    """Revoke the refresh token upstream (best effort) + delete the
    row. Returns ``True`` when a row was actually deleted, ``False``
    when there was nothing to disconnect."""
    row = await _da.get_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    if row is None:
        return False

    # Best-effort revoke — even if Google is unreachable we still
    # delete the row so the operator sees "Disconnected" immediately.
    try:
        refresh_token = decrypt_optional(row.refresh_token_encrypted)
        if refresh_token:
            await _oauth.revoke_refresh_token(refresh_token)
    except Exception:
        # Never let an upstream failure block the local disconnect.
        import logging

        logging.getLogger(__name__).exception(
            "google_calendar.disconnect revoke_failed org=%s user=%s",
            org_id,
            user_id,
        )

    await _da.delete_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    await session.commit()
    return True


async def get_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> CalendarConnectionStatus:
    """Read shape for the integrations card. ``connected=True`` iff a
    row exists AND its status is ``active``. Revoked / errored rows
    surface via the ``last_error`` field so the frontend can render a
    "Reconnect needed" state with a useful message."""
    row = await _da.get_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    if row is None:
        return CalendarConnectionStatus(
            connected=False,
            google_email=None,
            last_error=None,
            last_synced_at=None,
            scopes_granted=[],
        )
    return CalendarConnectionStatus(
        connected=row.status == "active",
        google_email=row.google_email,
        last_error=row.last_error,
        last_synced_at=row.last_synced_at,
        scopes_granted=list(row.scopes_granted or []),
    )


# --- Step 3 helpers — called from the sync task -----------------------


async def mark_row_error(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
    error: str,
) -> None:
    """Surface a per-token error on the integrations card. Called
    from the Step-4 Celery task's outer exception handler when the
    sync fails for a reason the sync loop hasn't already surfaced
    (e.g. an unhandled 5xx that exhausted the retry budget).

    Idempotent — if no row exists (revoked / never connected) this is
    a no-op. Owns its own commit so the caller can call it after a
    session rollback.
    """
    row = await _da.get_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    if row is None:
        return
    await _da.mark_status(
        session, token_id=row.id, status="error", error=error
    )
    await session.commit()


async def mark_row_synced(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> None:
    """Bump ``last_synced_at`` after a successful sync + clear any
    stale ``last_error``. Called from the Step-4 Celery task's happy
    path so the integrations card reflects the recent activity."""
    row = await _da.get_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    if row is None:
        return
    await _da.touch_last_synced(
        session, token_id=row.id, when=datetime.now(UTC)
    )
    if row.last_error is not None:
        await _da.mark_status(
            session, token_id=row.id, status="active", error=None
        )
    await session.commit()


__all__ = [
    "CalendarConnectionStatus",
    "build_authorize_url",
    "complete_connection",
    "disconnect",
    "get_status",
    "mark_row_error",
    "mark_row_synced",
]
