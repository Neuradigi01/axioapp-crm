import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.user import UserLogin, UserInfo
from src.models.password_reset import PasswordResetToken
from src.core.security.password import hash_password
from tests.conftest import test_engine, TestSession


@pytest_asyncio.fixture
async def client():
    from main import app
    import src.core.db as db_module

    original_session = db_module.async_session
    db_module.async_session = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    db_module.async_session = original_session


async def _seed_user(db):
    user = UserLogin(user_id="test_user", password=hash_password("user123"), is_active=True)
    db.add(user)
    await db.flush()
    info = UserInfo(member_id=user.id, first_name="Test", last_name="User",
                    email="user@test.com", mobile_no="1234567890")
    db.add(info)
    return user


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_password_reset_email", new_callable=AsyncMock)
async def test_forgot_password_existing_email(mock_email, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(db)
        await db.commit()

    resp = await client.post("/api/auth/forgot-password", json={
        "identifier": "user@test.com"
    })
    data = resp.json()
    assert data["success"] is True
    assert "reset link" in data["message"].lower() or "email exists" in data["message"].lower()
    mock_email.assert_called_once()


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_password_reset_email", new_callable=AsyncMock)
async def test_forgot_password_nonexistent_email(mock_email, mock_routes, client):
    resp = await client.post("/api/auth/forgot-password", json={
        "identifier": "nobody@test.com"
    })
    data = resp.json()
    # Should still return success (no email leak)
    assert data["success"] is True
    mock_email.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_password_reset_email", new_callable=AsyncMock)
async def test_reset_password_valid_token(mock_email, mock_routes, client):
    async with TestSession() as db:
        user = await _seed_user(db)
        token = PasswordResetToken(
            user_id=user.user_id,
            user_type="User",
            token="valid_token_123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(token)
        await db.commit()

    resp = await client.post("/api/auth/reset-password", json={
        "token": "valid_token_123", "new_password": "newpassword123"
    })
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Password changed successfully!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_reset_password_expired_token(mock_routes, client):
    async with TestSession() as db:
        user = await _seed_user(db)
        token = PasswordResetToken(
            user_id=user.user_id,
            user_type="User",
            token="expired_token_123",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(token)
        await db.commit()

    resp = await client.post("/api/auth/reset-password", json={
        "token": "expired_token_123", "new_password": "newpassword123"
    })
    data = resp.json()
    assert data["success"] is False
    assert "expired" in data["message"].lower() or "invalid" in data["message"].lower()


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_reset_password_used_token(mock_routes, client):
    async with TestSession() as db:
        user = await _seed_user(db)
        token = PasswordResetToken(
            user_id=user.user_id,
            user_type="User",
            token="used_token_123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_used=True,
        )
        db.add(token)
        await db.commit()

    resp = await client.post("/api/auth/reset-password", json={
        "token": "used_token_123", "new_password": "newpassword123"
    })
    data = resp.json()
    assert data["success"] is False
    assert "expired" in data["message"].lower() or "invalid" in data["message"].lower()


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_password_reset_email", new_callable=AsyncMock)
async def test_reset_password_invalidates_other_tokens(mock_email, mock_routes, client):
    from sqlalchemy import select

    async with TestSession() as db:
        user = await _seed_user(db)

        # Create two valid tokens for the same user
        token1 = PasswordResetToken(
            user_id=user.user_id, user_type="User", token="token_one",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        token2 = PasswordResetToken(
            user_id=user.user_id, user_type="User", token="token_two",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([token1, token2])
        await db.commit()

    # Use token_one to reset password
    resp = await client.post("/api/auth/reset-password", json={
        "token": "token_one", "new_password": "newpassword123"
    })
    assert resp.json()["success"] is True

    # Verify token_two is now invalidated
    async with TestSession() as db:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token == "token_two")
        other_token = (await db.execute(stmt)).scalar_one_or_none()
        assert other_token is not None
        assert other_token.is_used is True
