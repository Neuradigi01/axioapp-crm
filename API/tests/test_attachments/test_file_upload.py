import io
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.constants.route_ids import RouteIds
from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
from src.models.ticket import Ticket, TicketAttachment
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

    await db.commit()
    return admin, user, other


def _make_user_token(user_id="test_user"):
    return create_access_token(
        {
            "user_id": user_id,
            "role": "User",
            "access_rights": f"{RouteIds.USER_SUPPORT_COMPOSE},{RouteIds.USER_SUPPORT_TICKETS},{RouteIds.USER_SUPPORT_VIEW_TICKET}",
        }
    )


def _make_admin_token():
    return create_access_token(
        {
            "user_id": "test_admin",
            "role": "Admin",
            "access_rights": f"{RouteIds.ADMIN_SUPPORT_COMPOSE},{RouteIds.ADMIN_SUPPORT_TICKETS},{RouteIds.ADMIN_SUPPORT_VIEW_TICKET}",
            "is_super_admin": True,
        }
    )


# JPEG magic bytes (minimal valid JPEG header)
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 100

# PDF magic bytes
PDF_HEADER = b"%PDF-1.4 " + b"\x00" * 100

# ZIP magic bytes (used by .xlsx, .docx, etc.)
ZIP_HEADER = b"PK\x03\x04" + b"\x00" * 100

# EXE magic bytes (MZ header)
EXE_HEADER = b"MZ" + b"\x00" * 100


@pytest.mark.asyncio
async def test_upload_valid_image(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("photo.jpg", io.BytesIO(JPEG_HEADER), "image/jpeg"))],
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 1
    assert data["data"][0]["file_name"] == "photo.jpg"
    assert data["data"][0]["stored_name"].endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_valid_pdf(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("document.pdf", io.BytesIO(PDF_HEADER), "application/pdf"))],
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 1
    assert data["data"][0]["file_name"] == "document.pdf"


@pytest.mark.asyncio
async def test_upload_valid_excel(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "data.xlsx",
                    io.BytesIO(ZIP_HEADER),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ],
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data_count"] == 1
    assert data["data"][0]["file_name"] == "data.xlsx"


@pytest.mark.asyncio
async def test_upload_blocked_exe(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("malware.exe", io.BytesIO(EXE_HEADER), "application/octet-stream"))],
    )
    data = resp.json()
    assert data["success"] is False
    assert "not allowed" in data["message"].lower()


@pytest.mark.asyncio
async def test_upload_blocked_script(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    for ext, content_type in [
        (".js", "application/javascript"),
        (".bat", "application/x-bat"),
        (".ps1", "application/octet-stream"),
    ]:
        resp = await client.post(
            "/api/attachments/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=[("files", (f"script{ext}", io.BytesIO(b"some content"), content_type))],
        )
        data = resp.json()
        assert data["success"] is False, f"Expected {ext} to be blocked"
        assert "not allowed" in data["message"].lower()


@pytest.mark.asyncio
async def test_upload_disguised_exe(client):
    """An .exe file renamed to .jpg should be caught by MIME type check."""
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    # EXE content (MZ header) but claiming to be .jpg
    # The magic byte check should detect this isn't actually a JPEG
    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("fake.jpg", io.BytesIO(EXE_HEADER), "image/jpeg"))],
    )
    data = resp.json()
    assert data["success"] is False
    assert "does not match" in data["message"].lower() or "not allowed" in data["message"].lower()


@pytest.mark.asyncio
async def test_upload_too_large(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    # Create a file > 10MB
    large_content = JPEG_HEADER + b"\x00" * (11 * 1024 * 1024)

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("huge.jpg", io.BytesIO(large_content), "image/jpeg"))],
    )
    data = resp.json()
    assert data["success"] is False
    assert "large" in data["message"].lower() or "size" in data["message"].lower()


@pytest.mark.asyncio
async def test_upload_too_many_files(client):
    async with TestSession() as db:
        await _seed(db)

    token = _make_user_token()

    # 6 files — exceeds MAX_ATTACHMENTS (5)
    files = [("files", (f"photo{i}.jpg", io.BytesIO(JPEG_HEADER), "image/jpeg")) for i in range(6)]

    resp = await client.post(
        "/api/attachments/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )
    data = resp.json()
    assert data["success"] is False
    assert "too many" in data["message"].lower()


@pytest.mark.asyncio
async def test_download_as_participant(client):
    """Ticket participant can download an attachment."""
    async with TestSession() as db:
        await _seed(db)

        # Create a ticket with an attachment
        ticket = Ticket(
            ticket_no="TKT-000001",
            subject="Download test",
            message="Test message",
            from_user_id="test_user",
            from_user_type="User",
            to_user_id=None,
            to_user_type="Admin",
            status="Open",
            priority="Normal",
        )
        db.add(ticket)
        await db.flush()

        # Save a real file to disk for download
        from config import STATIC_DIR

        upload_dir = os.path.join(STATIC_DIR, "uploads", "tickets", "test")
        os.makedirs(upload_dir, exist_ok=True)
        stored_name = "test_download.jpg"
        file_path = os.path.join(upload_dir, stored_name)
        with open(file_path, "wb") as f:
            f.write(JPEG_HEADER)

        att = TicketAttachment(
            ticket_id=ticket.id,
            reply_id=None,
            file_name="original.jpg",
            stored_name=stored_name,
            file_path=f"uploads/tickets/test/{stored_name}",
            file_size=len(JPEG_HEADER),
            mime_type="image/jpeg",
            uploaded_by_id="test_user",
            uploaded_by_type="User",
        )
        db.add(att)
        await db.commit()

    token = _make_user_token("test_user")

    resp = await client.get(
        f"/api/attachments/{stored_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/jpeg")

    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)


@pytest.mark.asyncio
async def test_download_as_non_participant(client):
    """Non-participant should not be able to download attachments."""
    async with TestSession() as db:
        await _seed(db)

        ticket = Ticket(
            ticket_no="TKT-000002",
            subject="Private ticket",
            message="Private message",
            from_user_id="test_user",
            from_user_type="User",
            to_user_id=None,
            to_user_type="Admin",
            status="Open",
            priority="Normal",
        )
        db.add(ticket)
        await db.flush()

        att = TicketAttachment(
            ticket_id=ticket.id,
            reply_id=None,
            file_name="secret.pdf",
            stored_name="secret_file.pdf",
            file_path="uploads/tickets/test/secret_file.pdf",
            file_size=1024,
            mime_type="application/pdf",
            uploaded_by_id="test_user",
            uploaded_by_type="User",
        )
        db.add(att)
        await db.commit()

    # other_user is not a participant
    token = _make_user_token("other_user")

    resp = await client.get(
        "/api/attachments/secret_file.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is False
    assert "permission" in data["message"].lower()
