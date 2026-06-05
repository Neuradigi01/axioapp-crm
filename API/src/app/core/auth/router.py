"""Auth HTTP routes.

  POST /api/v1/auth/login    — exchange (email, password, org_slug) for a JWT
  POST /api/v1/auth/refresh  — rotate token_id; old session revoked
  POST /api/v1/auth/logout   — revoke current session

Rate limit: 10 login attempts per IP per minute (in-memory bucket from
`src.app.shared.rate_limit`). Refresh and logout are not rate-limited
— they require a valid bearer token already.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import service as auth_service
from src.app.core.auth.dependencies import get_current_user
from src.app.core.auth.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    SessionListResponse,
    SessionOut,
    SessionRevokeResponse,
)
from src.app.core.auth.tokens import InvalidToken, TokenClaims, decode_token
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db
from src.app.shared.rate_limit import login_limiter

router = APIRouter(prefix="/auth", tags=["Auth"])
_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _claims_from_bearer(creds: HTTPAuthorizationCredentials | None) -> TokenClaims:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    try:
        return decode_token(creds.credentials)
    except InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    rl = login_limiter.check(_client_ip(request))
    if not rl.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(int(rl.retry_after) + 1)},
        )

    return await auth_service.login(
        db,
        email=req.email,
        password=req.password,
        org_slug=req.org_slug,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    req: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Self-signup stage 1: create the user + a pending-template org.

    The org is a placeholder (`template_id="pending"`, name
    `"<First Name>'s Workspace"`). The returned JWT is a normal admin
    token; the response carries `needs_onboarding=true` so the
    frontend routes the user to `/onboarding` to pick a template.
    """
    return await auth_service.register_user_only(
        db,
        req=req,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )


@router.post(
    "/onboarding/complete",
    response_model=OnboardingCompleteResponse,
)
async def onboarding_complete(
    req: OnboardingCompleteRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingCompleteResponse:
    """Self-signup stage 2: finalize the pending-template org.

    Renames the org, sets the chosen `template_id`, runs the pack
    installer, and rotates the JWT. Caller's org must still be in
    `template_id="pending"` — already-onboarded users get 409.
    """
    ctx = get_context()
    if ctx.token_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token context",
        )
    return await auth_service.complete_onboarding(
        db,
        user=user,
        current_token_id=ctx.token_id,
        req=req,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    claims = _claims_from_bearer(creds)
    return await auth_service.refresh(db, claims)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    claims = _claims_from_bearer(creds)
    await auth_service.logout(db, claims.token_id)
    return LogoutResponse()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Last 50 sessions for the calling user, newest first.

    The current JWT is marked with `is_current=true` so the Settings →
    Login history tab can render the "This session" badge.
    """
    ctx = get_context()
    if ctx.token_id is None or user.legacy_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token context",
        )
    rows = await auth_service.list_user_sessions(
        db,
        user_id=user.legacy_uuid,
        current_token_id=ctx.token_id,
    )
    return SessionListResponse(
        sessions=[SessionOut(**row) for row in rows]
    )


@router.post(
    "/sessions/{session_id}/revoke", response_model=SessionRevokeResponse
)
async def revoke_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionRevokeResponse:
    """Revoke a single non-current session belonging to the caller.

    To revoke the current session, the client should call
    `POST /auth/logout` instead (this endpoint refuses to revoke it so a
    "Sign out" button click can't accidentally log you out of the tab
    you're using).
    """
    ctx = get_context()
    if ctx.token_id is None or user.legacy_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token context",
        )
    if session_id == ctx.token_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /auth/logout to end the current session.",
        )
    ok = await auth_service.revoke_user_session(
        db,
        user_id=user.legacy_uuid,
        session_id=session_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return SessionRevokeResponse()
