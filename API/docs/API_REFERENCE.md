# API Code Templates & Reference

> **Purpose:** Full code examples and templates for API development. Read `API_RULES.md` first for conventions.

---

## 1. Router Templates

### 1.1 Router `__init__.py` Pattern (Module Aggregation)
```python
# src/routers/auth/__init__.py

from fastapi import APIRouter

from .login import router as login_router
from .register import router as register_router
from .forgot_password import router as forgot_password_router

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

router.include_router(login_router)
router.include_router(register_router)
router.include_router(forgot_password_router)
```

### 1.2 Public Route (No Auth Required)
```python
# src/routers/auth/login.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import LoginRequest
from src.services.auth import login_service
from src.utilities.app_utils import get_real_client_ip, get_ip_info

router = APIRouter()


@router.post('/login')
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip_address = get_real_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    ip_info = await get_ip_info(ip_address)

    return await login_service.authenticate_user(
        db=db,
        identifier=req.identifier,
        password=req.password,
        ip_address=ip_address,
        user_agent=user_agent,
        ip_info=ip_info,
        two_factor_code=req.two_factor_code,
    )
```

### 1.3 Protected Route (Auth Required)
```python
# src/routers/user/profile.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.jwt import get_current_user
from src.services.user import user_service

router = APIRouter(
    dependencies=[Depends(get_current_user)]
)


@router.get('/profile')
async def get_profile(
    token_payload: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await user_service.get_profile(db, token_payload["user_id"])
```

### 1.4 Admin-Only Route (Role-Based)
```python
# src/routers/admin/users.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.jwt import get_current_user
from src.core.security.role_checker import RoleChecker
from src.services.admin import user_management_service

router = APIRouter(
    dependencies=[Depends(get_current_user)]
)


@router.post('/get_users', dependencies=[Depends(RoleChecker(['Admin']))])
async def get_users(
    req: GetUsersRequest,
    db: AsyncSession = Depends(get_db)
):
    return await user_management_service.get_users(db, req)
```

### 1.5 Registering Routes in Main Router
```python
# src/routers/__init__.py

from fastapi import APIRouter
from src.routers.auth import router as auth_router
from src.routers.user import router as user_router
from src.routers.admin import router as admin_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(user_router)
router.include_router(admin_router)
```

---

## 2. Business Layer Templates

### 2.1 Business Module Pattern
```python
# src/services/user/user_service.py

from sqlalchemy.ext.asyncio import AsyncSession
from src.data_access import user_da
from src.constants import messages


async def get_profile(db: AsyncSession, user_id: str) -> dict:
    user = await user_da.get_with_info(db, user_id)
    if not user:
        return {"success": False, "message": messages.USER_NOT_FOUND}

    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "user_id": user.user_id,
            "first_name": user.user_info.first_name,
            "last_name": user.user_info.last_name,
            "email": user.user_info.email,
        },
    }


async def change_password(db: AsyncSession, user_id: str, old_password: str, new_password: str) -> dict:
    user = await user_da.get_by_user_id(db, user_id)
    if not user:
        return {"success": False, "message": messages.USER_NOT_FOUND}

    if not verify_password(old_password, user.password):
        return {"success": False, "message": messages.INVALID_CREDENTIALS}

    await user_da.update_password(db, user_id, hash_password(new_password))
    await db.commit()

    return {"success": True, "message": messages.PASSWORD_CHANGED}
```

---

## 3. Data Access Layer Templates

### 3.1 DA Function Pattern
```python
# src/data_access/user_da.py

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.models.user import UserLogin, UserInfo


async def get_by_user_id(db: AsyncSession, user_id: str) -> UserLogin | None:
    stmt = select(UserLogin).where(func.lower(UserLogin.user_id) == user_id.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_with_info(db: AsyncSession, user_id: str) -> UserLogin | None:
    stmt = (
        select(UserLogin)
        .options(selectinload(UserLogin.user_info))
        .where(func.lower(UserLogin.user_id) == user_id.strip().lower())
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_info_by_email(db: AsyncSession, email: str) -> UserInfo | None:
    stmt = select(UserInfo).where(func.lower(UserInfo.email) == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_password(db: AsyncSession, user_id: str, hashed_password: str):
    stmt = (
        update(UserLogin)
        .where(func.lower(UserLogin.user_id) == user_id.strip().lower())
        .values(password=hashed_password)
    )
    await db.execute(stmt)
```

### 3.2 Key Rules
- Every function receives `db: AsyncSession` as first parameter
- Never call `db.commit()` — service layer handles commits
- Use `func.lower()` for case-insensitive user_id/email lookups
- Use `.strip().lower()` on input strings
- Return model instances or `None` — let service layer handle logic

---

## 4. Response Format Patterns

### Pattern 1: List with Pagination
```python
return {
    "success": True,
    "message": "OK",
    "data": users,
    "data_count": total_count
}
```

### Pattern 2: Single Action
```python
return {"success": True, "message": messages.PASSWORD_CHANGED}
```

### Pattern 3: Action with Return Data
```python
return {
    "success": True,
    "message": messages.OK,
    "data": {"token": token, "user_id": user.user_id, "role": "User"}
}
```

---

## 5. Core Module Templates

### 5.1 Database Connection & Dependency
```python
# src/core/db.py

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=20, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
```

### 5.2 JWT Security
```python
# src/core/security/jwt.py

from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import JWT_SECRET_KEY, JWT_ALGORITHM

security = HTTPBearer()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("user_id") is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
```

---

## 6. Token Payload Structure

**Never include internal DB IDs** (`member_id`, `admin.id`) in the JWT. Business layer resolves them internally via `user_id`.

```python
# User token
{
    "user_id": "john_doe",
    "role": "User",
    "access_rights": "1,2,10,12,13,14,15",
    "exp": 1234567890
}

# Admin token (super admin)
{
    "user_id": "admin",
    "role": "Admin",
    "access_rights": "1,2,11,20,21,22,23,30,31,32,40,41,42,43",
    "is_super_admin": True,
    "exp": 1234567890
}
```

---

## 7. WebSocket Templates

### 7.1 Event Constants (`src/constants/ws_events.py`)
```python
class ChatEvent:
    """Events for /ws/chat/* endpoints."""
    MESSAGE = "message"          # Incoming + broadcast
    TYPING = "typing"            # Incoming + broadcast
    PING = "ping"                # Incoming
    CONNECTION_ESTABLISHED = "connection_established"  # Outgoing
    MESSAGE_CONFIRMED = "message_confirmed"            # Outgoing
    PONG = "pong"                # Outgoing
    ERROR = "error"              # Outgoing
```

### 7.2 Channel Constants (`src/constants/ws_channels.py`)
```python
class WsChannel:
    CHAT = "chat:{conversation_id}"
    AGENT_CHATS = "agent:{member_id}:chats"
    ORG_QUEUE = "org:{org_member_id}:queue"
```

### 7.3 WS Emitter Pattern (`src/ws_emitters/`)
```python
# Emitter: explicit typed params, constructs payload internally
async def emit_message(
    conversation_id: int, *, message_id: int, sender_type: str,
    content: str, message_type: str, created_at: str, sender_id: str | None = None,
) -> None:
    """Broadcast a new message to a conversation channel."""
    await manager.publish(
        channel=WsChannel.CHAT.format(conversation_id=conversation_id),
        message_type=ChatEvent.MESSAGE,
        data={"id": message_id, "conversation_id": conversation_id, ...},
        sender_id=sender_id or "",
    )

# Service usage:
from src.ws_emitters import chat_ws_emitter
await chat_ws_emitter.emit_message(conv_id, message_id=msg.id, sender_type="visitor", ...)
```

---

## 8. Utility Functions Reference

```python
from src.core.security.password import hash_password, verify_password
from src.core.security.jwt import create_access_token, get_current_user
from src.utilities.aes_util import aes  # aes.encrypt(), aes.decrypt()
from src.utilities.app_utils import (
    get_real_client_ip,     # Get client IP from request
    generate_otp,           # Generate 6-digit OTP
    get_ip_info,            # Get IP geo info from ipinfo.io
    send_mail_async,        # Core email sender (checks EMAIL_ENABLED)
    send_sms_async,         # Core SMS sender (checks SMS_ENABLED)
    load_json,              # Load JSON file
)
```
