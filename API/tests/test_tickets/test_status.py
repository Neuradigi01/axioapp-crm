import pytest
import pytest_asyncio
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.models.ticket import Ticket
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


async def _seed(db, *, ticket_status="Open"):
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

    ticket = Ticket(
        ticket_no="TKT-000001",
        subject="Status test ticket",
        message="Testing status transitions",
        from_user_id="test_user",
        from_user_type="User",
        to_user_id=None,
        to_user_type="Admin",
        status=ticket_status,
        priority="Normal",
    )
    db.add(ticket)
    await db.flush()
    await db.commit()

    return admin, user, ticket


def _make_admin_token():
    return create_access_token({
        "user_id": "test_admin",
        "role": "Admin",
        "access_rights": f"{RouteIds.ADMIN_SUPPORT_VIEW_TICKET},{RouteIds.ADMIN_SUPPORT_TICKETS}",
        "is_super_admin": True,
    })


def _make_user_token():
    return create_access_token({
        "user_id": "test_user",
        "role": "User",
        "access_rights": f"{RouteIds.USER_SUPPORT_VIEW_TICKET},{RouteIds.USER_SUPPORT_TICKETS}",
    })


@pytest.mark.asyncio
async def test_admin_change_status_to_in_progress(client):
    async with TestSession() as db:
        admin, user, ticket = await _seed(db, ticket_status="Open")
        ticket_id = ticket.id

    token = _make_admin_token()

    resp = await client.put(
        f"/api/tickets/{ticket_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "In Progress"},
    )
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_admin_change_status_to_resolved(client):
    async with TestSession() as db:
        admin, user, ticket = await _seed(db, ticket_status="Open")
        ticket_id = ticket.id

    token = _make_admin_token()

    resp = await client.put(
        f"/api/tickets/{ticket_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "Resolved"},
    )
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_admin_close_ticket_sets_closed_at(client):
    async with TestSession() as db:
        admin, user, ticket = await _seed(db, ticket_status="Open")
        ticket_id = ticket.id

    token = _make_admin_token()

    resp = await client.put(
        f"/api/tickets/{ticket_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "Closed"},
    )
    data = resp.json()
    assert data["success"] is True

    # Verify closed_at and closed_by are set
    async with TestSession() as db:
        from sqlalchemy import select
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        result = await db.execute(stmt)
        updated = result.scalar_one()
        assert updated.status == "Closed"
        assert updated.closed_at is not None
        assert updated.closed_by == "test_admin"


@pytest.mark.asyncio
async def test_user_cannot_change_status(client):
    async with TestSession() as db:
        admin, user, ticket = await _seed(db, ticket_status="Open")
        ticket_id = ticket.id

    # User token — should not be able to access admin status endpoint
    token = _make_user_token()

    resp = await client.put(
        f"/api/tickets/{ticket_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "In Progress"},
    )
    assert resp.status_code == 403
