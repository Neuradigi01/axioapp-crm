from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from config import JWT_ALGORITHM, JWT_SECRET_KEY
from src.core.db import async_session
from src.models.login_history import LoginHistory

security = HTTPBearer()
SECRET_KEY = JWT_SECRET_KEY
ALGORITHM = JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        token_id = payload.get("token_id")
        if user_id is None or token_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        async with async_session() as db:
            result = await db.execute(
                select(LoginHistory.is_token_active).where(LoginHistory.id == token_id)
            )
            is_active = result.scalar_one_or_none()
            if not is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been invalidated"
                )

        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from None
