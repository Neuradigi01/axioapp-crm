import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.models.routes import Route
from src.core.security.password import hash_password, verify_password
from src.core.security.jwt import create_access_token
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


async def _seed(db):
    admin = Admin(
        admin_user_id="test_admin",
        password=hash_password("admin123"),
        name="Test Admin",
        email="admin@test.com",
        is_super_admin=True,
        is_active=True,
    )
    db.add(admin)

    # Create routes for user management (route IDs 31, 32)
    routes = [
        Route(parent_id=0, control_id="admin_user_list", user_type="Admin",
              name="User List", path="users", url="/admin/users",
              is_nav_menu_item=True, order_no=1, is_compulsory=False),
        Route(parent_id=0, control_id="admin_user_detail", user_type="Admin",
              name="User Detail", path="users/:id", url="/admin/users/:id",
              is_nav_menu_item=False, order_no=2, is_compulsory=False),
    ]
    db.add_all(routes)

    # Create test users
    users = []
    for i in range(5):
        user = UserLogin(
            user_id=f"user_{i}",
            password=hash_password("pass123"),
            is_active=i < 3,  # first 3 active, last 2 inactive
        )
        db.add(user)
        await db.flush()
        info = UserInfo(
            member_id=user.id,
            first_name=f"First{i}",
            last_name=f"Last{i}",
            email=f"user{i}@test.com",
            mobile_no=f"12345{i:05d}",
        )
        db.add(info)
        users.append(user)

    await db.flush()
    return admin, routes, users


def _make_admin_token(route_ids):
    return create_access_token({
        "user_id": "test_admin",
        "role": "Admin",
        "access_rights": ",".join(str(r) for r in route_ids),
        "is_super_admin": True,
    })


@pytest.mark.asyncio
async def test_get_users_list_with_search(client):
    async with TestSession() as db:
        admin, routes, users = await _seed(db)
        await db.commit()
        route_ids = [r.id for r in routes]

    token = _make_admin_token(route_ids)

    resp = await client.post(
        "/api/admin/users/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"search": "First0", "page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["first_name"] == "First0"


@pytest.mark.asyncio
async def test_get_users_list_with_status_filter(client):
    async with TestSession() as db:
        admin, routes, users = await _seed(db)
        await db.commit()
        route_ids = [r.id for r in routes]

    token = _make_admin_token(route_ids)

    # Filter active users only
    resp = await client.post(
        "/api/admin/users/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": True, "page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 3

    # Filter inactive users only
    resp2 = await client.post(
        "/api/admin/users/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": False, "page_index": 0, "page_size": 10},
    )
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["data_count"] == 2


@pytest.mark.asyncio
async def test_get_user_detail(client):
    async with TestSession() as db:
        admin, routes, users = await _seed(db)
        await db.commit()
        route_ids = [r.id for r in routes]

    token = _make_admin_token(route_ids)

    resp = await client.get(
        "/api/admin/users/user_0",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["user_id"] == "user_0"
    assert data["data"]["first_name"] == "First0"
    assert data["data"]["email"] == "user0@test.com"
    assert "total_referrals" in data["data"]
    assert "open_tickets" in data["data"]


@pytest.mark.asyncio
async def test_toggle_user_status(client):
    async with TestSession() as db:
        admin, routes, users = await _seed(db)
        await db.commit()
        route_ids = [r.id for r in routes]

    token = _make_admin_token(route_ids)

    resp = await client.put(
        "/api/admin/users/toggle-status",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "user_0", "is_active": False},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Status updated successfully!"

    # Verify status changed
    resp2 = await client.get(
        "/api/admin/users/user_0",
        headers={"Authorization": f"Bearer {token}"},
    )
    data2 = resp2.json()
    assert data2["data"]["is_active"] is False


@pytest.mark.asyncio
async def test_admin_change_user_password(client):
    async with TestSession() as db:
        admin, routes, users = await _seed(db)
        await db.commit()
        route_ids = [r.id for r in routes]

    token = _make_admin_token(route_ids)

    resp = await client.post(
        "/api/admin/users/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "user_0", "new_password": "newpassword123"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Password reset successfully!"


@pytest.mark.asyncio
async def test_user_management_requires_admin_role(client):
    async with TestSession() as db:
        route = Route(
            parent_id=0, control_id="user_dashboard", user_type="User",
            name="Dashboard", path="dashboard", url="/user/dashboard",
            is_nav_menu_item=True, order_no=1, is_compulsory=True,
        )
        db.add(route)
        await db.flush()
        await db.commit()
        route_id = route.id

    # User token - should not access admin endpoints
    token = create_access_token({
        "user_id": "test_user",
        "role": "User",
        "access_rights": str(route_id),
    })

    resp = await client.post(
        "/api/admin/users/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 0, "page_size": 10},
    )
    assert resp.status_code == 403
