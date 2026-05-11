import pytest
import pytest_asyncio
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.models.ticket import Ticket, TicketReply, TicketAttachment
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

    # Another user (non-participant)
    other = UserLogin(
        user_id="other_user",
        password=hash_password("other123"),
        is_active=True,
    )
    db.add(other)
    await db.flush()

    other_info = UserInfo(
        member_id=other.id,
        first_name="Other",
        last_name="User",
        email="other@test.com",
        mobile_no="9876543210",
    )
    db.add(other_info)

    ticket = Ticket(
        ticket_no="TKT-000001",
        subject="Test ticket",
        message="Initial message",
        from_user_id="test_user",
        from_user_type="User",
        to_user_id=None,
        to_user_type="Admin",
        status=ticket_status,
        priority="Normal",
    )
    db.add(ticket)
    await db.flush()

    return admin, user, other, ticket


def _make_user_token(user_id="test_user"):
    return create_access_token({
        "user_id": user_id,
        "role": "User",
        "access_rights": f"{RouteIds.USER_SUPPORT_VIEW_TICKET},{RouteIds.USER_SUPPORT_COMPOSE},{RouteIds.USER_SUPPORT_TICKETS}",
    })


def _make_admin_token():
    return create_access_token({
        "user_id": "test_admin",
        "role": "Admin",
        "access_rights": f"{RouteIds.ADMIN_SUPPORT_VIEW_TICKET},{RouteIds.ADMIN_SUPPORT_COMPOSE},{RouteIds.ADMIN_SUPPORT_TICKETS}",
        "is_super_admin": True,
    })


@pytest.mark.asyncio
async def test_view_ticket_returns_conversation_thread(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        reply = TicketReply(
            ticket_id=ticket.id,
            message="Admin reply",
            replied_by_id="test_admin",
            replied_by_type="Admin",
            is_read=False,
        )
        db.add(reply)
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["thread"]) == 2
    assert data["data"]["thread"][0]["type"] == "message"
    assert data["data"]["thread"][1]["type"] == "reply"


@pytest.mark.asyncio
async def test_view_ticket_includes_attachments(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        att = TicketAttachment(
            ticket_id=ticket.id,
            reply_id=None,
            file_name="doc.pdf",
            stored_name="abc123.pdf",
            file_path="uploads/tickets/abc123.pdf",
            file_size=2048,
            mime_type="application/pdf",
            uploaded_by_id="test_user",
            uploaded_by_type="User",
        )
        db.add(att)
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is True
    attachments = data["data"]["thread"][0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["file_name"] == "doc.pdf"


@pytest.mark.asyncio
async def test_view_marks_unread_as_read(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        reply = TicketReply(
            ticket_id=ticket.id,
            message="Admin reply",
            replied_by_id="test_admin",
            replied_by_type="Admin",
            is_read=False,
        )
        db.add(reply)
        await db.commit()
        ticket_id = ticket.id
        reply_id = reply.id

    token = _make_user_token("test_user")

    # View the ticket — should mark admin's reply as read for User reader
    resp = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["success"] is True

    # Verify the reply is now marked as read
    async with TestSession() as db:
        from sqlalchemy import select
        from src.models.ticket import TicketReply as TR
        stmt = select(TR).where(TR.id == reply_id)
        result = await db.execute(stmt)
        updated_reply = result.scalar_one()
        assert updated_reply.is_read is True


@pytest.mark.asyncio
async def test_reply_to_ticket_adds_message(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.post(
        f"/api/tickets/{ticket_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "User follow-up", "attachments": []},
    )
    data = resp.json()
    assert data["success"] is True

    # Verify reply was added
    resp2 = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data2 = resp2.json()
    assert len(data2["data"]["thread"]) == 2
    assert data2["data"]["thread"][1]["message"] == "User follow-up"


@pytest.mark.asyncio
async def test_reply_with_attachments(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.post(
        f"/api/tickets/{ticket_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "See attached",
            "attachments": [
                {
                    "stored_name": "reply_file.jpg",
                    "file_name": "screenshot.jpg",
                    "file_size": 5120,
                    "mime_type": "image/jpeg",
                },
            ],
        },
    )
    data = resp.json()
    assert data["success"] is True

    # Verify reply has attachment
    resp2 = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data2 = resp2.json()
    reply_entry = data2["data"]["thread"][1]
    assert len(reply_entry["attachments"]) == 1
    assert reply_entry["attachments"][0]["file_name"] == "screenshot.jpg"


@pytest.mark.asyncio
async def test_reply_to_resolved_reopens_ticket(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db, ticket_status="Resolved")
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.post(
        f"/api/tickets/{ticket_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Not resolved yet", "attachments": []},
    )
    assert resp.json()["success"] is True

    # Verify ticket was reopened
    resp2 = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data2 = resp2.json()
    assert data2["data"]["status"] == "Open"


@pytest.mark.asyncio
async def test_reply_to_closed_ticket_fails(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db, ticket_status="Closed")
        await db.commit()
        ticket_id = ticket.id

    token = _make_user_token("test_user")

    resp = await client.post(
        f"/api/tickets/{ticket_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Trying to reply", "attachments": []},
    )
    data = resp.json()
    assert data["success"] is False
    assert "closed" in data["message"].lower()


@pytest.mark.asyncio
async def test_cannot_view_others_ticket(client):
    async with TestSession() as db:
        admin, user, other, ticket = await _seed(db)
        await db.commit()
        ticket_id = ticket.id

    # other_user is NOT a participant of this ticket
    token = _make_user_token("other_user")

    resp = await client.get(
        f"/api/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is False
    assert "permission" in data["message"].lower()
