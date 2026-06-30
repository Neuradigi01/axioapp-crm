from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, SMS_ENABLED
from src.app.core.auth.two_factor import data_access
from src.providers import otp_provider, two_factor_provider

# `purpose` value written to `tbl_otps.purpose` so the otp lookup in
# `otp_provider.verify_otp(..., "login")` matches what was issued.
_OTP_PURPOSE = "login"


@dataclass(frozen=True, slots=True)
class TwoFactorState:
    enabled: bool
    method: str | None
    secret: str | None


@dataclass(frozen=True, slots=True)
class TwoFactorChallenge:
    """Returned when 2FA is required but no code was supplied yet.

    `method` is the user's preferred method (or the first available one
    if the preferred is no longer usable — e.g. EMAIL_ENABLED flipped off).
    `available_methods` lets the UI offer "try another way".
    """

    method: str
    available_methods: list[str]


def _available_methods(state: TwoFactorState, email: str | None, mobile: str | None) -> list[str]:
    methods: list[str] = []
    if EMAIL_ENABLED and email:
        methods.append("email")
    if SMS_ENABLED and mobile:
        methods.append("sms")
    if state.secret:
        methods.append("authenticator")
    return methods


async def _load_state(db: AsyncSession, member_id: int) -> TwoFactorState:
    row = await data_access.get_two_factor_columns(db, member_id=member_id)
    if row is None:
        return TwoFactorState(enabled=False, method=None, secret=None)
    enabled, method, secret = row
    return TwoFactorState(enabled=enabled, method=method, secret=secret)


async def _send_or_noop(
    db: AsyncSession,
    *,
    method: str,
    member_id: int,
    email: str | None,
    mobile: str | None,
) -> None:
    """Dispatch the chosen method's OTP (no-op for authenticator)."""
    if method == "email":
        await otp_provider.send_otp_email(db, member_id, "User", email, _OTP_PURPOSE)
    elif method == "sms":
        await otp_provider.send_otp_sms(db, member_id, "User", mobile, _OTP_PURPOSE)
    # authenticator → user reads code from their app, server does nothing here


async def enforce_at_login(
    db: AsyncSession,
    *,
    member_id: int,
    email: str | None,
    mobile: str | None,
    submitted_code: str | None,
    submitted_method: str | None,
) -> TwoFactorChallenge | None:
    """Gate the login flow on 2FA when the user has it enabled.

    Returns:
      * `None` when 2FA is off OR the submitted code passed → caller
        proceeds to mint the access token.
      * `TwoFactorChallenge(...)` when no code was submitted and the
        user must be prompted (OTP has been dispatched for email/sms).
      * raises HTTP 401 when a code was submitted but invalid.
      * raises HTTP 500 when 2FA is enabled but the user has no usable
        method (config drift — e.g. EMAIL_ENABLED off + no authenticator
        secret). Surfaces as a 500 rather than a silent bypass.
    """
    state = await _load_state(db, member_id)
    if not state.enabled:
        return None

    available = _available_methods(state, email, mobile)
    preferred = state.method if state.method in available else (available[0] if available else None)
    if preferred is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No 2FA method available for this account",
        )

    if not submitted_code:
        await _send_or_noop(db, method=preferred, member_id=member_id, email=email, mobile=mobile)
        await db.commit()
        return TwoFactorChallenge(method=preferred, available_methods=available)

    method = submitted_method if submitted_method in available else preferred
    if method == "authenticator":
        verified = two_factor_provider.verify_totp_code(state.secret, submitted_code)
    else:
        verified = await otp_provider.verify_otp(db, member_id, submitted_code, _OTP_PURPOSE)

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA code",
        )
    return None


@dataclass(frozen=True, slots=True)
class TryAnotherWayResult:
    method: str
    available_methods: list[str]


async def switch_method(
    db: AsyncSession,
    *,
    member_id: int,
    email: str | None,
    mobile: str | None,
    method: str,
) -> TryAnotherWayResult:
    """Re-dispatch the 2FA challenge via the requested `method`.

    Caller (the router) has already re-verified the user's password and
    confirmed the account exists. This function:
      * Confirms 2FA is enabled for the user.
      * Confirms `method` is in the available list.
      * Sends OTP via that method (or no-op for authenticator).

    Raises 400 on disabled 2FA or unavailable method.
    """
    state = await _load_state(db, member_id)
    if not state.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled for this account",
        )
    available = _available_methods(state, email, mobile)
    if method not in available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Method '{method}' is not available",
        )

    await _send_or_noop(db, method=method, member_id=member_id, email=email, mobile=mobile)
    await db.commit()
    return TryAnotherWayResult(method=method, available_methods=available)
