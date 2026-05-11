import pytest
import pytest_asyncio
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.core.security.password import hash_password
from src.core.security.jwt import create_access_token
from src.constants.route_ids import RouteIds
from tests.conftest import test_engine, TestSession


@pytest_asyncio.fixture
async def client():
    from main import app
    import src.core.db as db_module

    original_session = db_module.async_session
    db_module.async_session = TestSession

    await test_engine.dispose()
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
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
    await db.commit()

    return admin, user


def _make_user_token():
    return create_access_token({
        "user_id": "test_user",
        "role": "User",
        "access_rights": f"{RouteIds.USER_SUPPORT_COMPOSE},{RouteIds.USER_SUPPORT_TICKETS}",
    })


def _make_admin_token():
    return create_access_token({
        "user_id": "test_admin",
        "role": "Admin",
        "access_rights": f"{RouteIds.ADMIN_SUPPORT_COMPOSE},{RouteIds.ADMIN_SUPPORT_TICKETS}",
        "is_super_admin": True,
    })


@pytest.mark.asyncio
async def test_user_compose_ticket(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/tickets/compose",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "subject": "Test ticket",
            "message": "Hello, I need help",
            "priority": "Normal",
            "attachments": [],
        },
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["ticket_no"].startswith("TKT-")


@pytest.mark.asyncio
async def test_user_compose_with_attachments(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/tickets/compose",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "subject": "With attachment",
            "message": "See attached file",
            "priority": "Normal",
            "attachments": [
                {
                    "stored_name": "abc123.jpg",
                    "file_name": "photo.jpg",
                    "file_size": 1024,
                    "mime_type": "image/jpeg",
                },
            ],
        },
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["ticket_no"].startswith("TKT-")


@pytest.mark.asyncio
async def test_admin_compose_to_user(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_admin_token()

    resp = await client.post(
        "/api/tickets/compose",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_user_id": "test_user",
            "subject": "Admin notice",
            "message": "Please update your profile",
            "priority": "Normal",
            "attachments": [],
        },
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["ticket_no"].startswith("TKT-")


@pytest.mark.asyncio
async def test_admin_compose_invalid_user(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_admin_token()

    resp = await client.post(
        "/api/tickets/compose",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_user_id": "nonexistent_user",
            "subject": "Test",
            "message": "Test message",
            "priority": "Normal",
            "attachments": [],
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert "not found" in data["message"].lower()
