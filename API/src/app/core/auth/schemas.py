"""Pydantic v2 request/response shapes for the auth router."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Plain str (not EmailStr): the step spec uses `admin@demo.local`, which
    # RFC 6761 reserves and EmailStr rejects. Login does not need strict
    # email validation — the actual check is DB row match.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    # Optional — when omitted, the server resolves the user's org from the
    # email via the active `tbl_organization_members` row. Used by the demo
    # pill (which sends an explicit slug) and by manual login (which doesn't).
    org_slug: str | None = Field(default=None, min_length=1, max_length=64)
    # Two-factor fields. When the user has 2FA enabled, the first POST is
    # made without these; the response is a `TwoFactorChallengeResponse`
    # that tells the UI which method to prompt for. The UI submits a
    # second POST with `two_factor_code` (and optionally
    # `two_factor_method` if the user picked an alternative).
    two_factor_code: str | None = Field(default=None, min_length=1, max_length=12)
    two_factor_method: Literal["authenticator", "email", "sms"] | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


class TwoFactorChallengeResponse(BaseModel):
    """Returned by `POST /auth/login` when the user has 2FA enabled and
    no code was submitted. The OTP (for email/sms) has already been
    dispatched; the UI prompts the user and re-POSTs `/auth/login` with
    the code in `two_factor_code`."""
    requires_two_factor: Literal[True] = True
    method: str
    available_methods: list[str]


class TryAnotherWayRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    org_slug: str | None = Field(default=None, min_length=1, max_length=64)
    method: Literal["authenticator", "email", "sms"]


class TryAnotherWayResponse(BaseModel):
    method: str
    available_methods: list[str]


class RefreshResponse(LoginResponse):
    """Same shape as LoginResponse — the new rotated JWT."""


class LogoutResponse(BaseModel):
    success: bool = True


class RegisterRequest(BaseModel):
    """Body for the layered self-signup endpoint.

    Self-signup collects user identity only. The organization name and
    vertical-pack choice come later, on `/auth/onboarding/complete`
    (the dedicated post-register onboarding page). EmailStr is
    intentionally avoided to match the LoginRequest decision (local
    `.local` TLDs must be representable in dev).

    Pydantic v2 default `extra="ignore"` means clients that still send
    a legacy `organization_name` field get silently accepted (no 422) —
    the field is dropped before reaching the service.
    """
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    organization_id: uuid.UUID
    organization_slug: str
    role_name: str
    # `True` for self-signup (org is in `template_id="pending"` state and
    # the user must finish the onboarding picker). `False` for the
    # legacy `register_with_new_org` path, which still ships an org
    # with a real pack installed (kept for seed scripts and any direct
    # callers).
    needs_onboarding: bool = True


class OnboardingCompleteRequest(BaseModel):
    """Body for `POST /api/v1/auth/onboarding/complete`.

    Sent by the onboarding page after self-signup. `template_id` must
    correspond to an `available` tile in the catalog (onboarding-setup
    Step 1); coming-soon tiles are rejected with 400.
    """

    organization_name: str = Field(min_length=1, max_length=128)
    template_id: str = Field(min_length=1, max_length=32)
    country: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    team_size: str | None = Field(default=None, max_length=32)


class OnboardingCompleteResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    organization_id: uuid.UUID
    organization_slug: str
    role_name: str
    needs_onboarding: bool = False


class SessionOut(BaseModel):
    """One `auth_sessions` row, scoped to the caller's own user_id.

    `is_current` is `True` for the JWT making the request — the frontend
    uses it to mark that row "This session" and hide the Sign-out button.
    Used by the Settings → Login history tab.
    """
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    ip: str | None
    ua: str | None
    is_current: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionOut]


class SessionRevokeResponse(BaseModel):
    success: bool = True


class TwoFactorStatusResponse(BaseModel):
    """Read-only 2FA state for the calling user.

    Reads the legacy `tbl_user_login.two_factor_enabled` /
    `two_factor_method` columns (the layered `User` mapper excludes
    them, so we read via the legacy `UserLogin` mapping). The settings
    page surfaces this for visibility; in-dashboard enrol / disable
    lives in a dedicated future track since it needs ActionToken
    re-auth and TOTP secret rotation.
    """
    enabled: bool
    method: str | None
