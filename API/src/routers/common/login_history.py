from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.route_ids import RouteIds
from src.core.db import get_db
from src.core.security.access_guard import AccessGuard
from src.schemas.login_history import LoginHistoryListRequest, LogoutSessionRequest
from src.services.auth import login_history_service

router = APIRouter(prefix="/login-history", tags=["Login History"])


@router.post("/list")
async def get_login_history(
    req: LoginHistoryListRequest,
    token_payload: dict = Depends(
        AccessGuard([RouteIds.USER_LOGIN_HISTORY, RouteIds.ADMIN_LOGIN_HISTORY])
    ),
    db: AsyncSession = Depends(get_db),
):
    role = token_payload["role"]
    if role != "Admin":
        req.user_id = token_payload["user_id"]
        req.match_exact_user_id = True

    return await login_history_service.get_login_history(
        db,
        user_id=req.user_id or None,
        match_exact=req.match_exact_user_id,
        page_index=req.page_index,
        page_size=req.page_size,
        current_token_id=token_payload.get("token_id", 0),
    )


@router.post("/logout-session")
async def logout_session(
    req: LogoutSessionRequest,
    token_payload: dict = Depends(
        AccessGuard([RouteIds.USER_LOGIN_HISTORY, RouteIds.ADMIN_LOGIN_HISTORY])
    ),
    db: AsyncSession = Depends(get_db),
):
    return await login_history_service.logout_session(
        db,
        token_id=req.token_id,
        current_user_id=token_payload["user_id"],
        current_user_type=token_payload["role"],
    )


@router.get("/logout")
async def logout_current(
    token_payload: dict = Depends(
        AccessGuard([RouteIds.USER_LOGIN_HISTORY, RouteIds.ADMIN_LOGIN_HISTORY])
    ),
    db: AsyncSession = Depends(get_db),
):
    return await login_history_service.logout_current(
        db,
        token_id=token_payload.get("token_id", 0),
        user_id=token_payload["user_id"],
        user_type=token_payload["role"],
    )
