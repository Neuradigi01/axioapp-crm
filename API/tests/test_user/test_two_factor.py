from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
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


async def _seed(db, two_factor_enabled=False, two_factor_method=None, two_factor_secret=None):
    user = UserLogin(
        user_id="test_user",
        password=hash_password("user123"),
        is_active=True,
        two_factor_enabled=two_factor_enabled,
        two_factor_method=two_factor_method or "",
        two_factor_secret=two_factor_secret or "",
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

    # 2FA route (user route_id=14)
    route = Route(
        parent_id=0,
        control_id="user_2fa",
        user_type="User",
        name="2FA Settings",
        path="2fa",
        url="/user/2fa",
        is_nav_menu_item=True,
        order_no=4,
        is_compulsory=True,
    )
    db.add(route)
    await db.flush()

    return user, info, route


def _make_token(route_id):
    return create_access_token(
        {
            "user_id": "test_user",
            "role": "User",
            "access_rights": str(route_id),
        }
    )


@pytest.mark.asyncio
@patch("src.services.two_factor_service.generate_totp_secret", return_value="JBSWY3DPEHPK3PXP")
@patch("src.services.two_factor_service.generate_qr_code", return_value="data:image/png;base64,abc")
async def test_setup_authenticator_returns_qr(mock_qr, mock_secret, client):
    async with TestSession() as db:
        user, info, route = await _seed(db)
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)
    resp = await client.post(
        "/api/2fa/setup-authenticator",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["secret"] == "JBSWY3DPEHPK3PXP"
    assert "qr_code" in data["data"]


@pytest.mark.asyncio
@patch("src.services.two_factor_service.generate_totp_secret", return_value="JBSWY3DPEHPK3PXP")
@patch("src.services.two_factor_service.generate_qr_code", return_value="data:image/png;base64,abc")
@patch("src.services.two_factor_service.verify_totp_code", return_value=True)
async def test_verify_and_enable_authenticator(mock_verify, mock_qr, mock_secret, client):
    async with TestSession() as db:
        user, info, route = await _seed(db)
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)

    # First setup authenticator to store the secret
    await client.post(
        "/api/2fa/setup-authenticator",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123"},
    )

    # Then verify and enable
    resp = await client.post(
        "/api/2fa/verify-and-enable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "code": "123456", "method": "authenticator"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Two-factor authentication enabled!"


@pytest.mark.asyncio
@patch("src.services.otp_service.send_otp_email", new_callable=AsyncMock)
@patch("src.services.otp_service.verify_otp", new_callable=AsyncMock, return_value=True)
async def test_enable_email_otp(mock_verify, mock_send, client):
    async with TestSession() as db:
        user, info, route = await _seed(db)
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)

    # Send setup OTP
    await client.post(
        "/api/2fa/send-setup-otp",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "method": "email"},
    )

    # Verify and enable
    resp = await client.post(
        "/api/2fa/verify-and-enable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "code": "123456", "method": "email"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Two-factor authentication enabled!"


@pytest.mark.asyncio
@patch("src.services.two_factor_service.verify_totp_code", return_value=True)
async def test_disable_2fa_with_valid_code(mock_verify, client):
    async with TestSession() as db:
        user, info, route = await _seed(
            db,
            two_factor_enabled=True,
            two_factor_method="authenticator",
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)

    resp = await client.post(
        "/api/2fa/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "code": "123456"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Two-factor authentication disabled!"


@pytest.mark.asyncio
@patch("src.services.two_factor_service.verify_totp_code", return_value=False)
async def test_disable_2fa_with_invalid_code(mock_verify, client):
    async with TestSession() as db:
        user, info, route = await _seed(
            db,
            two_factor_enabled=True,
            two_factor_method="authenticator",
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)

    resp = await client.post(
        "/api/2fa/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "code": "000000"},
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Invalid or expired OTP!"


@pytest.mark.asyncio
@patch("src.services.two_factor_service.verify_totp_code", return_value=True)
async def test_change_method_from_authenticator_to_email(mock_verify, client):
    async with TestSession() as db:
        user, info, route = await _seed(
            db,
            two_factor_enabled=True,
            two_factor_method="authenticator",
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )
        await db.commit()
        route_id = route.id

    token = _make_token(route_id)

    resp = await client.post(
        "/api/2fa/change-method",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "user123", "current_code": "123456", "new_method": "email"},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Two-factor method changed to email!"
