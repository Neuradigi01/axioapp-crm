from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.routes import Route
from src.models.user import UserInfo, UserLogin
from tests.conftest import TestSession, test_engine


@pytest_asyncio.fixture
async def client():
    import src.core.db as db_module
    from main import app

    original_session = db_module.async_session
    db_module.async_session = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    db_module.async_session = original_session


async def _seed_user_with_routes(db):
    user = UserLogin(
        user_id="test_user",
        password=hash_password("user123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    info = UserInfo(
        member_id=user.id,
        first_name="Test",
        last_name="User",
        email="user@test.com",
        mobile_no="1234567890",
    )
    db.add(info)

    route = Route(
        parent_id=0,
        control_id="user_dashboard",
        user_type="User",
        name="Dashboard",
        path="dashboard",
        url="/user/dashboard",
        is_nav_menu_item=True,
        order_no=1,
        is_compulsory=True,
    )
    db.add(route)
    await db.flush()

    return user, info, route


@pytest.mark.asyncio
@patch("src.data_access.ticket_da.get_open_ticket_count", new_callable=AsyncMock, return_value=2)
async def test_get_dashboard_returns_user_stats(mock_tickets, client):
    async with TestSession() as db:
        user, info, route = await _seed_user_with_routes(db)
        await db.commit()
        route_id = route.id

    token = create_access_token(
        {
            "user_id": "test_user",
            "role": "User",
            "access_rights": str(route_id),
        }
    )

    resp = await client.get("/api/user/dashboard", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert data["data"]["first_name"] == "Test"
    assert data["data"]["last_name"] == "User"
    assert data["data"]["email"] == "user@test.com"
    assert "two_factor_enabled" in data["data"]
    assert "referral_count" in data["data"]


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client):
    resp = await client.get("/api/user/dashboard")
    assert resp.status_code == 403
