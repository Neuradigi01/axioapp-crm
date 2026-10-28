from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
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


async def _seed_admin_with_routes(db):
    admin = Admin(
        admin_user_id="test_admin",
        password=hash_password("admin123"),
        name="Test Admin",
        email="admin@test.com",
        is_super_admin=True,
        is_active=True,
    )
    db.add(admin)

    route = Route(
        parent_id=0,
        control_id="admin_dashboard",
        user_type="Admin",
        name="Dashboard",
        path="dashboard",
        url="/admin/dashboard",
        is_nav_menu_item=True,
        order_no=1,
        is_compulsory=True,
    )
    db.add(route)
    await db.flush()

    return admin, route


@pytest.mark.asyncio
@patch("src.data_access.ticket_da.get_total_count", new_callable=AsyncMock, return_value=5)
@patch(
    "src.data_access.ticket_da.get_total_count_by_status", new_callable=AsyncMock, return_value=2
)
async def test_admin_dashboard_returns_stats(mock_open, mock_total, client):
    async with TestSession() as db:
        admin, route = await _seed_admin_with_routes(db)

        # Add a test user for registration stats
        user = UserLogin(user_id="user1", password=hash_password("pass123"), is_active=True)
        db.add(user)
        await db.flush()
        info = UserInfo(
            member_id=user.id, first_name="John", last_name="Doe", email="john@test.com"
        )
        db.add(info)
        await db.commit()
        route_id = route.id

    token = create_access_token(
        {
            "user_id": "test_admin",
            "role": "Admin",
            "access_rights": str(route_id),
        }
    )

    resp = await client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert "total_users" in data["data"]
    assert "active_users" in data["data"]
    assert "inactive_users" in data["data"]
    assert "sub_admin_count" in data["data"]
    assert "last_10_registrations" in data["data"]


@pytest.mark.asyncio
async def test_admin_dashboard_requires_admin_role(client):
    async with TestSession() as db:
        # Create user route only
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
        await db.commit()
        route_id = route.id

    # User token with user route - should not have access to admin dashboard
    token = create_access_token(
        {
            "user_id": "test_user",
            "role": "User",
            "access_rights": str(route_id),
        }
    )

    resp = await client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
