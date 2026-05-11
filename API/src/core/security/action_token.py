import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.jwt import get_current_user
from src.data_access import action_token_da
from src.constants import messages
from config import JWT_SECRET_KEY, JWT_ALGORITHM, ACTION_TOKEN_EXPIRY_MINUTES

SECRET_KEY = JWT_SECRET_KEY
ALGORITHM = JWT_ALGORITHM


def create_action_token(user_id: str, user_type: str) -> tuple[str, str, datetime]:
    jti = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACTION_TOKEN_EXPIRY_MINUTES)
    payload = {
        "sub": user_id,
        "role": user_type,
        "purpose": "action_verify",
        "jti": jti,
        "exp": expires_at,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_action_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "action_verify":
            return None
        return payload
    except JWTError:
        return None


def _make_error_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "success": False,
            "message": message,
            "error_code": error_code,
        },
    )


class ActionTokenGuard:
    """
    FastAPI dependency that enforces action token verification when 2FA is enabled.

    Usage in routers:
        Depends(ActionTokenGuard())

    Behavior:
    - If user has 2FA disabled: passes through (no verification needed)
    - If user has 2FA enabled and valid X-Action-Token header: passes through
    - If user has 2FA enabled and no/invalid token: raises HTTP 403 with error_code
    """

    async def __call__(
        self,
        request: Request,
        token_payload: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        from src.data_access import user_da, admin_da

        user_id = token_payload.get("user_id")
        user_type = token_payload.get("role")

        if user_type == "User":
            record = await user_da.get_by_user_id(db, user_id)
        else:
            record = await admin_da.get_by_user_id(db, user_id)

        if not record or not record.two_factor_enabled:
            return

        token_str = request.headers.get("X-Action-Token")
        if not token_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": messages.ACTION_2FA_REQUIRED,
                    "error_code": "2FA_REQUIRED",
                },
            )

        payload = decode_action_token(token_str)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": messages.ACTION_TOKEN_INVALID,
                    "error_code": "ACTION_TOKEN_INVALID",
                },
            )

        if payload.get("sub") != user_id or payload.get("role") != user_type:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": messages.ACTION_TOKEN_INVALID,
                    "error_code": "ACTION_TOKEN_INVALID",
                },
            )

        jti = payload.get("jti")
        if await action_token_da.is_token_used(db, jti):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": messages.ACTION_TOKEN_ALREADY_USED,
                    "error_code": "ACTION_TOKEN_USED",
                },
            )

        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        await action_token_da.mark_token_used(db, jti, record.id, user_type, expires_at)
