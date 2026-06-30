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
        id=70,
        parent_id=11,
        control_id="admin_contact_us",
        user_type="Admin",
        name="Contact Us",
        path="contact-us",
        url="/admin/contact-us",
        is_nav_menu_item=True,
        order_no=8,
        is_compulsory=False,
    )
    db.add(route)
    await db.commit()

    token = create_access_token(
        {
            "user_id": admin.admin_user_id,
            "role": "Admin",
            "admin_id": admin.id,
            "access_rights": "70",
        }
    )
    return admin, token


async def _submit_contact(
    client,
    name="John Doe",
    email="john@example.com",
    contact_type="General",
    subject="Test",
    message="Hello",
):
    return await client.post(
        "/api/misc/contact-us",
        json={
            "name": name,
            "email": email,
            "type": contact_type,
            "subject": subject,
            "message": message,
        },
    )


# ── Public Submit Endpoint ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_contact_us_success(client):
    res = await _submit_contact(client)
    data = res.json()
    assert res.status_code == 200
    assert data["success"] is True
    assert data["message"] == "OK"


@pytest.mark.asyncio
async def test_submit_contact_us_all_types(client):
    for contact_type in ["General", "Support", "Feedback"]:
        res = await _submit_contact(client, contact_type=contact_type)
        assert res.json()["success"] is True


@pytest.mark.asyncio
async def test_submit_contact_us_missing_fields(client):
    res = await client.post(
        "/api/misc/contact-us",
        json={
            "name": "John",
            "email": "john@example.com",
        },
    )
    assert res.status_code == 422


# ── Admin List Endpoint ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_requires_auth(client):
    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
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
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
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
async def test_admin_list_returns_submitted_contacts(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(
        client, name="Alice", email="alice@test.com", contact_type="General", subject="Hello"
    )
    await _submit_contact(
        client, name="Bob", email="bob@test.com", contact_type="Support", subject="Help"
    )
    await _submit_contact(
        client, name="Carol", email="carol@test.com", contact_type="Feedback", subject="Nice"
    )

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
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
async def test_admin_list_search_by_name(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(client, name="Alice Smith", email="alice@test.com", subject="Q1")
    await _submit_contact(client, name="Bob Jones", email="bob@test.com", subject="Q2")

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "Alice",
            "type": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["name"] == "Alice Smith"


@pytest.mark.asyncio
async def test_admin_list_search_by_email(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(client, name="Alice", email="alice@unique.com", subject="Q1")
    await _submit_contact(client, name="Bob", email="bob@other.com", subject="Q2")

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "unique",
            "type": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["email"] == "alice@unique.com"


@pytest.mark.asyncio
async def test_admin_list_search_by_subject(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(client, name="Alice", subject="Billing Question")
    await _submit_contact(client, name="Bob", subject="General Inquiry")

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "billing",
            "type": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["subject"] == "Billing Question"


@pytest.mark.asyncio
async def test_admin_list_filter_by_type(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(client, contact_type="General")
    await _submit_contact(client, contact_type="Support")
    await _submit_contact(client, contact_type="Support")
    await _submit_contact(client, contact_type="Feedback")

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "Support",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 2
    assert all(d["type"] == "Support" for d in data["data"])


@pytest.mark.asyncio
async def test_admin_list_pagination(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    for i in range(5):
        await _submit_contact(client, name=f"User {i}", email=f"user{i}@test.com")

    # Page 1
    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
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
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
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

    await _submit_contact(client, name="Alice", contact_type="Support", subject="Help me")
    await _submit_contact(client, name="Alice", contact_type="General", subject="Hello")
    await _submit_contact(client, name="Bob", contact_type="Support", subject="Issue")

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "Alice",
            "type": "Support",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    data = res.json()
    assert data["data_count"] == 1
    assert data["data"][0]["name"] == "Alice"
    assert data["data"][0]["type"] == "Support"


@pytest.mark.asyncio
async def test_admin_list_response_fields(client):
    async with TestSession() as db:
        _, token = await _seed_admin_with_route(db)

    await _submit_contact(
        client,
        name="Alice",
        email="alice@test.com",
        contact_type="Feedback",
        subject="Great",
        message="Love it",
    )

    res = await client.post(
        "/api/admin/contact-us/list",
        json={
            "search": "",
            "type": "all",
            "page_index": 0,
            "page_size": 10,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    item = res.json()["data"][0]
    assert "id" in item
    assert item["name"] == "Alice"
    assert item["email"] == "alice@test.com"
    assert item["type"] == "Feedback"
    assert item["subject"] == "Great"
    assert item["message"] == "Love it"
    assert "created_at" in item
