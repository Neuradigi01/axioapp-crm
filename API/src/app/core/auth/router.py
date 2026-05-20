"""Auth HTTP routes.

  POST /api/v1/auth/login    — exchange (email, password, org_slug) for a JWT
  POST /api/v1/auth/refresh  — rotate token_id; old session revoked
  POST /api/v1/auth/logout   — revoke current session

Rate limit: 10 login attempts per IP per minute (in-memory bucket from
`src.app.shared.rate_limit`). Refresh and logout are not rate-limited
— they require a valid bearer token already.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import service as auth_service
from src.app.core.auth.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
)
from src.app.core.auth.tokens import InvalidToken, TokenClaims, decode_token
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
    """Self-signup: creates a new org, makes the visitor its Owner, returns a JWT."""
    return await auth_service.register_with_new_org(
        db,
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
