import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.user import UserLogin, UserInfo
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


VALID_REGISTER_DATA = {
    "password": "password123",
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@test.com",
}


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_welcome_email", new_callable=AsyncMock)
async def test_register_success(mock_email, mock_routes, client):
    resp = await client.post("/api/auth/register", json=VALID_REGISTER_DATA)
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert data["message"] == "Registration successful!"
    # Server auto-generates user_id and returns it
    assert "user_id" in data["data"]
    assert len(data["data"]["user_id"]) > 0


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_welcome_email", new_callable=AsyncMock)
async def test_register_duplicate_email(mock_email, mock_routes, client):
    # Create existing user with the same email
    async with TestSession() as db:
        user = UserLogin(user_id="other_user", password=hash_password("pass1234"), is_active=True)
        db.add(user)
        await db.flush()
        info = UserInfo(member_id=user.id, first_name="Other", last_name="User",
                        email="john@test.com", mobile_no="")
        db.add(info)
        await db.commit()

    resp = await client.post("/api/auth/register", json=VALID_REGISTER_DATA)
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Email already registered!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_welcome_email", new_callable=AsyncMock)
async def test_register_with_valid_referral(mock_email, mock_routes, client):
    # Create the referral user
    async with TestSession() as db:
        referrer = UserLogin(user_id="referrer", password=hash_password("pass1234"), is_active=True)
        db.add(referrer)
        await db.flush()
        info = UserInfo(member_id=referrer.id, first_name="Ref", last_name="User",
                        email="referrer@test.com", mobile_no="")
        db.add(info)
        await db.commit()

    data = {**VALID_REGISTER_DATA, "referral_id": "referrer"}
    resp = await client.post("/api/auth/register", json=data)
    result = resp.json()
    assert result["success"] is True
    assert result["message"] == "Registration successful!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.services.email_service.send_welcome_email", new_callable=AsyncMock)
async def test_register_with_invalid_referral(mock_email, mock_routes, client):
    data = {**VALID_REGISTER_DATA, "referral_id": "nonexistent_user"}
    resp = await client.post("/api/auth/register", json=data)
    result = resp.json()
    assert result["success"] is False
    assert "Invalid referral" in result["message"]


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_register_password_too_short(mock_routes, client):
    data = {**VALID_REGISTER_DATA, "password": "short"}
    resp = await client.post("/api/auth/register", json=data)
    assert resp.status_code == 422  # Pydantic validation error
