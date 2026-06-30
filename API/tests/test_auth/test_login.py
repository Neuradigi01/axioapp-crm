from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
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


async def _seed_user(
    db,
    user_id="test_user",
    password="user123",
    is_active=True,
    two_factor_enabled=False,
    two_factor_method=None,
    two_factor_secret=None,
):
    user = UserLogin(
        user_id=user_id,
        password=hash_password(password),
        is_active=is_active,
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
        email=f"{user_id}@test.com",
        mobile_no="1234567890",
    )
    db.add(info)
    return user


async def _seed_admin(
    db, admin_user_id="test_admin", password="admin123", is_super_admin=True, is_active=True
):
    admin = Admin(
        admin_user_id=admin_user_id,
        password=hash_password(password),
        name="Test Admin",
        email=f"{admin_user_id}@test.com",
        is_super_admin=is_super_admin,
        is_active=is_active,
    )
    db.add(admin)
    await db.flush()
    return admin


async def _seed_routes(db):
    routes = [
        Route(
            parent_id=0,
            control_id="admin_dashboard",
            user_type="Admin",
            name="Dashboard",
            path="dashboard",
            url="/admin/dashboard",
            is_nav_menu_item=True,
            order_no=1,
            is_compulsory=True,
        ),
        Route(
            parent_id=0,
            control_id="user_dashboard",
            user_type="User",
            name="Dashboard",
            path="dashboard",
            url="/user/dashboard",
            is_nav_menu_item=True,
            order_no=2,
            is_compulsory=True,
        ),
        Route(
            parent_id=0,
            control_id="any_route",
            user_type="Any",
            name="Logout",
            path="logout",
            url="/logout",
            is_nav_menu_item=False,
            order_no=99,
            is_compulsory=True,
        ),
    ]
    db.add_all(routes)
    await db.flush()
    return routes


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_user_login_success(mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(db)
        await _seed_routes(db)
        await db.commit()

    resp = await client.post(
        "/api/auth/login", json={"identifier": "test_user", "password": "user123"}
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert "token" in data["data"]
    assert data["data"]["role"] == "User"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_user_login_wrong_password(mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(db)
        await db.commit()

    resp = await client.post(
        "/api/auth/login", json={"identifier": "test_user", "password": "wrong"}
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Invalid credentials!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_user_login_nonexistent_user(mock_ip, mock_routes, client):
    resp = await client.post(
        "/api/auth/login", json={"identifier": "nobody", "password": "pass123"}
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Invalid credentials!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_user_login_inactive_user(mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(db, is_active=False)
        await db.commit()

    resp = await client.post(
        "/api/auth/login", json={"identifier": "test_user", "password": "user123"}
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Invalid credentials!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
@patch("src.services.otp_service.send_otp_email", new_callable=AsyncMock)
async def test_user_login_2fa_required(mock_otp, mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(db, two_factor_enabled=True, two_factor_method="email")
        await db.commit()

    resp = await client.post(
        "/api/auth/login", json={"identifier": "test_user", "password": "user123"}
    )
    data = resp.json()
    assert data["success"] is False
    assert data["data"]["requires_2fa"] is True
    assert data["data"]["method"] == "email"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
@patch("src.services.two_factor_service.verify_totp_code", return_value=True)
async def test_user_login_2fa_valid_code(mock_totp, mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(
            db,
            two_factor_enabled=True,
            two_factor_method="authenticator",
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )
        await _seed_routes(db)
        await db.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"identifier": "test_user", "password": "user123", "two_factor_code": "123456"},
    )
    data = resp.json()
    assert data["success"] is True
    assert "token" in data["data"]


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
@patch("src.services.two_factor_service.verify_totp_code", return_value=False)
async def test_user_login_2fa_invalid_code(mock_totp, mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_user(
            db,
            two_factor_enabled=True,
            two_factor_method="authenticator",
            two_factor_secret="JBSWY3DPEHPK3PXP",
        )
        await db.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"identifier": "test_user", "password": "user123", "two_factor_code": "000000"},
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Invalid or expired OTP!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_admin_login_success(mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_admin(db)
        await _seed_routes(db)
        await db.commit()

    resp = await client.post(
        "/api/auth/admin-login", json={"identifier": "test_admin", "password": "admin123"}
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert data["data"]["role"] == "Admin"
    assert "token" in data["data"]


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_admin_login_super_admin_gets_all_rights(mock_ip, mock_routes, client):
    async with TestSession() as db:
        await _seed_admin(db, is_super_admin=True)
        await _seed_routes(db)
        await db.commit()

    resp = await client.post(
        "/api/auth/admin-login", json={"identifier": "test_admin", "password": "admin123"}
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["is_super_admin"] is True
    # Super admin should have access_rights in token — verify token contains admin + any routes
    from src.core.security.jwt import ALGORITHM, SECRET_KEY, jwt

    payload = jwt.decode(data["data"]["token"], SECRET_KEY, algorithms=[ALGORITHM])
    rights = {int(r) for r in payload["access_rights"].split(",") if r.strip()}
    # Should include admin_dashboard route id and any_route id
    assert len(rights) >= 2


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_admin_login_sub_admin_gets_assigned_rights(mock_ip, mock_routes, client):
    from src.models.routes import AdminRoute

    async with TestSession() as db:
        admin = await _seed_admin(db, is_super_admin=False)
        routes = await _seed_routes(db)
        await db.flush()

        # Assign only the admin_dashboard route to this sub-admin
        admin_route = AdminRoute(
            admin_id=admin.id,
            route_id=routes[0].id,  # admin_dashboard
            assigned_by=admin.id,
        )
        db.add(admin_route)
        await db.commit()

    resp = await client.post(
        "/api/auth/admin-login", json={"identifier": "test_admin", "password": "admin123"}
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["is_super_admin"] is False

    from src.core.security.jwt import ALGORITHM, SECRET_KEY, jwt

    payload = jwt.decode(data["data"]["token"], SECRET_KEY, algorithms=[ALGORITHM])
    rights = {int(r) for r in payload["access_rights"].split(",") if r.strip()}
    # Should include the assigned route + compulsory routes, but not user_dashboard
    assert routes[0].id in rights  # admin_dashboard (assigned)
    assert routes[2].id in rights  # any_route (compulsory)
