import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.constants.route_ids import RouteIds
from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
from src.models.ticket import Ticket
from src.models.user import UserInfo, UserLogin
from tests.conftest import TestSession, test_engine


@pytest_asyncio.fixture
async def client():
    import src.core.db as db_module
    from main import app

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


async def _seed_with_tickets(db):
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

    # Create tickets from user to admin
    tickets = []
    for i in range(5):
        status = "Open" if i < 3 else "Resolved"
        ticket = Ticket(
            ticket_no=f"TKT-{i + 1:06d}",
            subject=f"Test ticket {i + 1}",
            message=f"Message body {i + 1}",
            from_user_id="test_user",
            from_user_type="User",
            to_user_id=None,
            to_user_type="Admin",
            status=status,
            priority="Normal",
        )
        db.add(ticket)
        tickets.append(ticket)

    await db.commit()
    return admin, user, tickets


def _make_user_token():
    return create_access_token(
        {
            "user_id": "test_user",
            "role": "User",
            "access_rights": f"{RouteIds.USER_SUPPORT_TICKETS},{RouteIds.USER_SUPPORT_VIEW_TICKET}",
        }
    )


def _make_admin_token():
    return create_access_token(
        {
            "user_id": "test_admin",
            "role": "Admin",
            "access_rights": f"{RouteIds.ADMIN_SUPPORT_TICKETS},{RouteIds.ADMIN_SUPPORT_VIEW_TICKET}",
            "is_super_admin": True,
        }
    )


@pytest.mark.asyncio
async def test_user_inbox_shows_own_tickets(client):
    async with TestSession() as db:
        await _seed_with_tickets(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 5


@pytest.mark.asyncio
async def test_user_inbox_filter_by_status(client):
    async with TestSession() as db:
        await _seed_with_tickets(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "Open", "page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 3

    resp2 = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "Resolved", "page_index": 0, "page_size": 10},
    )
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["data_count"] == 2


@pytest.mark.asyncio
async def test_user_inbox_search_by_subject(client):
    async with TestSession() as db:
        await _seed_with_tickets(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"search_term": "ticket 1", "page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 1
    assert "ticket 1" in data["data"][0]["subject"].lower()


@pytest.mark.asyncio
async def test_user_inbox_pagination(client):
    async with TestSession() as db:
        await _seed_with_tickets(db)

    token = _make_user_token()

    # Page 1: 2 items
    resp = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 0, "page_size": 2},
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 2
    assert data["data_count"] == 5

    # Page 2: 2 items
    resp2 = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 1, "page_size": 2},
    )
    data2 = resp2.json()
    assert data2["success"] is True
    assert len(data2["data"]) == 2

    # Page 3: 1 item
    resp3 = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 2, "page_size": 2},
    )
    data3 = resp3.json()
    assert data3["success"] is True
    assert len(data3["data"]) == 1


@pytest.mark.asyncio
async def test_admin_list_shows_all_tickets(client):
    async with TestSession() as db:
        await _seed_with_tickets(db)

    token = _make_admin_token()

    resp = await client.post(
        "/api/tickets/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 0, "page_size": 10},
    )
    data = resp.json()
    assert data["success"] is True
    # Admin sees all tickets
    assert data["data_count"] == 5
