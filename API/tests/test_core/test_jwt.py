import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException

from src.core.security.jwt import create_access_token, get_current_user, SECRET_KEY, ALGORITHM


def test_create_token_returns_string():
    token = create_access_token({"user_id": "test", "role": "User"})
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_valid_token():
    payload_data = {"user_id": "test_user", "role": "User", "member_id": 1}
    token = create_access_token(payload_data)
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["user_id"] == "test_user"
    assert decoded["role"] == "User"
    assert decoded["member_id"] == 1


def test_expired_token_raises():
    payload = {"user_id": "test", "role": "User", "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    from unittest.mock import AsyncMock, MagicMock
    credentials = MagicMock()
    credentials.credentials = token

    with pytest.raises(HTTPException) as exc_info:
        import asyncio
        asyncio.get_event_loop().run_until_complete(get_current_user(credentials))
    assert exc_info.value.status_code == 401


def test_invalid_token_raises():
    from unittest.mock import MagicMock
    credentials = MagicMock()
    credentials.credentials = "garbage.token.string"

    with pytest.raises(HTTPException) as exc_info:
        import asyncio
        asyncio.get_event_loop().run_until_complete(get_current_user(credentials))
    assert exc_info.value.status_code == 401


def test_token_contains_required_fields():
    payload_data = {"user_id": "admin01", "role": "Admin", "admin_id": 1, "access_rights": "1,2,3"}
    token = create_access_token(payload_data)
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert "user_id" in decoded
    assert "role" in decoded
    assert "access_rights" in decoded
    assert "exp" in decoded
