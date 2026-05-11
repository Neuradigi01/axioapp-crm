import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.user import UserLogin, UserInfo
from src.models.routes import Route
from src.core.security.password import hash_password
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
    )
    db.add(info)

    route = Route(
        parent_id=0, control_id="user_change_password", user_type="User",
        name="Change Password", path="change-password", url="/user/change-password",
        is_nav_menu_item=True, order_no=3, is_compulsory=True,
    )
    db.add(route)
    await db.flush()

    return user, route


@pytest.mark.asyncio
async def test_change_password_success(client):
    async with TestSession() as db:
        user, route = await _seed(db)
        await db.commit()
        route_id = route.id

    token = create_access_token({
        "user_id": "test_user",
        "role": "User",
        "access_rights": str(route_id),
    })

    resp = await client.post(
        "/api/user/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "user123", "new_password": "newpass123"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Password changed successfully!"


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(client):
    async with TestSession() as db:
        user, route = await _seed(db)
        await db.commit()
        route_id = route.id

    token = create_access_token({
        "user_id": "test_user",
        "role": "User",
        "access_rights": str(route_id),
    })

    resp = await client.post(
        "/api/user/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "wrongpass", "new_password": "newpass123"},
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Old password is incorrect!"


@pytest.mark.asyncio
async def test_change_password_requires_auth(client):
    resp = await client.post(
        "/api/user/change-password",
        json={"old_password": "user123", "new_password": "newpass123"},
    )
    assert resp.status_code == 403
