import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
from src.models.routes import Route
from tests.conftest import (
    TestSession,
    _patch_all_async_sessions,
    _restore_all_async_sessions,
    test_engine,
)


@pytest_asyncio.fixture
async def client():
    from main import app

    originals = _patch_all_async_sessions()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    _restore_all_async_sessions(originals)


async def _seed_admin_with_route(db):
    admin = Admin(
        admin_user_id="test_admin",
        password=hash_password("admin123"),
        name="Test Admin",
        email="admin@test.com",
        is_super_admin=True,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    route = Route(
        id=74,
        parent_id=11,
        control_id="admin_newsletter",
        user_type="Admin",
        name="Newsletter",
        path="newsletter",
        url="/admin/newsletter",
        is_nav_menu_item=True,
        order_no=12,
        is_compulsory=False,
    )
    db.add(route)
    await db.commit()

    token = create_access_token(
        {
            "user_id": admin.admin_user_id,
            "role": "Admin",
            "admin_id": admin.id,
            "access_rights": "74",
        }
    )
    return admin, token


async def _subscribe(client, email="subscriber@example.com"):
    return await client.post("/api/misc/newsletter/subscribe", json={"email": email})


async def _unsubscribe(client, email="subscriber@example.com"):
    return await client.post("/api/misc/newsletter/unsubscribe", json={"email": email})


# ── Public Subscribe Endpoint ─────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_success(client):
    res = await _subscribe(client)
    data = res.json()
    assert res.status_code == 200
    assert data["success"] is True
    assert data["message"] == "OK"


@pytest.mark.asyncio
async def test_subscribe_duplicate_email_upserts(client):
    await _subscribe(client, email="dup@test.com")
    res = await _subscribe(client, email="dup@test.com")
    data = res.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_subscribe_resubscribe_after_unsubscribe(client):
    await _subscribe(client, email="toggle@test.com")
    await _unsubscribe(client, email="toggle@test.com")
    res = await _subscribe(client, email="toggle@test.com")
    assert res.json()["success"] is True

    # Verify via admin list
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "toggle@test.com",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["is_subscribed"] is True


@pytest.mark.asyncio
async def test_subscribe_missing_email(client):
    res = await client.post("/api/misc/newsletter/subscribe", json={})
    assert res.status_code == 422


# ── Public Unsubscribe Endpoint ───────────────────────────────────


@pytest.mark.asyncio
async def test_unsubscribe_success(client):
    await _subscribe(client, email="unsub@test.com")
    res = await _unsubscribe(client, email="unsub@test.com")
    data = res.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_email(client):
    res = await _unsubscribe(client, email="noone@test.com")
    data = res.json()
    assert data["success"] is True


# ── Admin List Endpoint ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_requires_auth(client):
    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_empty(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["success"] is True
    assert data["data"] == []
    assert data["data_count"] == 0


@pytest.mark.asyncio
async def test_admin_list_returns_subscribers(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="a@test.com")
    await _subscribe(client, email="b@test.com")
    await _subscribe(client, email="c@test.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["success"] is True
    assert data["data_count"] == 3
    assert len(data["data"]) == 3


@pytest.mark.asyncio
async def test_admin_list_search_by_email(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="alice@unique.com")
    await _subscribe(client, email="bob@other.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "unique",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["email"] == "alice@unique.com"


@pytest.mark.asyncio
async def test_admin_list_filter_subscribed(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="active@test.com")
    await _subscribe(client, email="gone@test.com")
    await _unsubscribe(client, email="gone@test.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "subscribed",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["email"] == "active@test.com"
    assert data["data"][0]["is_subscribed"] is True


@pytest.mark.asyncio
async def test_admin_list_filter_unsubscribed(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="active@test.com")
    await _subscribe(client, email="gone@test.com")
    await _unsubscribe(client, email="gone@test.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "unsubscribed",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["email"] == "gone@test.com"
    assert data["data"][0]["is_subscribed"] is False


@pytest.mark.asyncio
async def test_admin_list_pagination(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    for i in range(5):
        await _subscribe(client, email=f"user{i}@test.com")

    # Page 1
    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 0,
            "page_size": 2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 5
    assert len(data["data"]) == 2

    # Page 3 (last)
    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 2,
            "page_size": 2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 5
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_admin_list_search_and_filter_combined(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="alice@domain.com")
    await _subscribe(client, email="alice@other.com")
    await _unsubscribe(client, email="alice@other.com")
    await _subscribe(client, email="bob@domain.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "alice",
            "status": "subscribed",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["email"] == "alice@domain.com"


@pytest.mark.asyncio
async def test_admin_list_response_fields(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _subscribe(client, email="fields@test.com")

    res = await client.post(
        "/api/admin/newsletter/list",
        json={
            "search": "",
            "status": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    item = res.json()["data"][0]
    assert "id" in item
    assert item["email"] == "fields@test.com"
    assert item["is_subscribed"] is True
    assert "created_at" in item
    assert "updated_at" in item
