import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.models.routes import Route, AdminRoute
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
    admin = Admin(
        admin_user_id="super_admin",
        password=hash_password("admin123"),
        name="Super Admin",
        email="superadmin@test.com",
        is_super_admin=True,
        is_active=True,
    )
    db.add(admin)

    # Admin routes: compulsory dashboard + non-compulsory sub-admin management routes
    routes = [
        Route(parent_id=0, control_id="admin_dashboard", user_type="Admin",
              name="Dashboard", path="dashboard", url="/admin/dashboard",
              is_nav_menu_item=True, order_no=1, is_compulsory=True),
        Route(parent_id=0, control_id="admin_sub_admins_list", user_type="Admin",
              name="Sub Admins", path="sub-admins", url="/admin/sub-admins",
              is_nav_menu_item=True, order_no=2, is_compulsory=False),
        Route(parent_id=0, control_id="any_logout", user_type="Any",
              name="Logout", path="logout", url="/logout",
              is_nav_menu_item=False, order_no=99, is_compulsory=True),
    ]
    db.add_all(routes)
    await db.flush()

    return admin, routes


def _make_super_admin_token(route_ids):
    return create_access_token({
        "user_id": "super_admin",
        "role": "Admin",
        "access_rights": ",".join(str(r) for r in route_ids),
        "is_super_admin": True,
    })


@pytest.mark.asyncio
async def test_create_sub_admin_success(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.post(
        "/api/admin/sub-admins/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "admin_user_id": "sub_admin_1",
            "password": "subadmin123",
            "name": "Sub Admin One",
            "email": "sub1@test.com",
            "route_ids": [all_ids[1]],
        },
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Sub-admin created successfully!"


@pytest.mark.asyncio
async def test_create_sub_admin_duplicate_user_id(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    # Create first sub-admin
    await client.post(
        "/api/admin/sub-admins/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "admin_user_id": "sub_admin_dup",
            "password": "subadmin123",
            "name": "Sub Admin",
        },
    )

    # Try creating duplicate
    resp = await client.post(
        "/api/admin/sub-admins/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "admin_user_id": "sub_admin_dup",
            "password": "subadmin123",
            "name": "Sub Admin Duplicate",
        },
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "User ID already exists!"


@pytest.mark.asyncio
async def test_get_sub_admin_list_with_pagination(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)

        # Create a few sub-admins
        for i in range(3):
            sub = Admin(
                admin_user_id=f"sub_{i}",
                password=hash_password("pass123"),
                name=f"Sub Admin {i}",
                email=f"sub{i}@test.com",
                is_super_admin=False,
                is_active=True,
                created_by=admin.id,
            )
            db.add(sub)

        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.post(
        "/api/admin/sub-admins/list",
        headers={"Authorization": f"Bearer {token}"},
        json={"page_index": 0, "page_size": 2},
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 2
    assert data["data_count"] == 3


@pytest.mark.asyncio
async def test_update_sub_admin_routes(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)

        sub = Admin(
            admin_user_id="sub_routes",
            password=hash_password("pass123"),
            name="Sub Routes",
            is_super_admin=False,
            is_active=True,
            created_by=admin.id,
        )
        db.add(sub)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.put(
        "/api/admin/sub-admins/routes",
        headers={"Authorization": f"Bearer {token}"},
        json={"admin_id": "sub_routes", "route_ids": [all_ids[1]]},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Routes updated successfully!"

    # Verify routes were assigned
    resp2 = await client.get(
        "/api/admin/sub-admins/sub_routes",
        headers={"Authorization": f"Bearer {token}"},
    )
    data2 = resp2.json()
    assert all_ids[1] in data2["data"]["route_ids"]


@pytest.mark.asyncio
async def test_assignable_routes_excludes_compulsory(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.get(
        "/api/admin/sub-admins/assignable-routes",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    assert data["success"] is True

    # Only non-compulsory routes should appear
    returned_ids = [r["id"] for r in data["data"]]
    # admin_dashboard (compulsory) should NOT be in the list
    assert all_ids[0] not in returned_ids
    # any_logout (compulsory) should NOT be in the list
    assert all_ids[2] not in returned_ids
    # sub-admin list route (non-compulsory) SHOULD be in the list
    assert all_ids[1] in returned_ids


@pytest.mark.asyncio
async def test_toggle_sub_admin_status(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)

        sub = Admin(
            admin_user_id="sub_toggle",
            password=hash_password("pass123"),
            name="Sub Toggle",
            is_super_admin=False,
            is_active=True,
            created_by=admin.id,
        )
        db.add(sub)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.put(
        "/api/admin/sub-admins/toggle-status",
        headers={"Authorization": f"Bearer {token}"},
        json={"admin_id": "sub_toggle", "is_active": False},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "Status updated successfully!"


@pytest.mark.asyncio
async def test_cannot_deactivate_super_admin(client):
    async with TestSession() as db:
        admin, routes = await _seed(db)

        # Create another super admin to try deactivating
        other_super = Admin(
            admin_user_id="other_super",
            password=hash_password("pass123"),
            name="Other Super",
            is_super_admin=True,
            is_active=True,
        )
        db.add(other_super)
        await db.commit()
        all_ids = [r.id for r in routes]

    token = _make_super_admin_token(all_ids)

    resp = await client.put(
        "/api/admin/sub-admins/toggle-status",
        headers={"Authorization": f"Bearer {token}"},
        json={"admin_id": "other_super", "is_active": False},
    )
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "Cannot deactivate a super admin!"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
@patch("src.utilities.app_utils.get_ip_info", new_callable=AsyncMock, return_value={})
async def test_sub_admin_login_gets_only_assigned_routes(mock_ip, mock_routes, client):
    async with TestSession() as db:
        admin, routes = await _seed(db)

        sub = Admin(
            admin_user_id="sub_login",
            password=hash_password("sub123"),
            name="Sub Login",
            is_super_admin=False,
            is_active=True,
            created_by=admin.id,
        )
        db.add(sub)
        await db.flush()

        # Assign only the non-compulsory route
        ar = AdminRoute(admin_id=sub.id, route_id=routes[1].id, assigned_by=admin.id)
        db.add(ar)
        await db.commit()

        compulsory_ids = {routes[0].id, routes[2].id}  # dashboard + logout (compulsory)
        assigned_id = routes[1].id

    resp = await client.post(
        "/api/auth/admin-login",
        json={"identifier": "sub_login", "password": "sub123"},
    )
    data = resp.json()
    assert data["success"] is True

    from src.core.security.jwt import jwt, SECRET_KEY, ALGORITHM
    payload = jwt.decode(data["data"]["token"], SECRET_KEY, algorithms=[ALGORITHM])
    rights = {int(r) for r in payload["access_rights"].split(",") if r.strip()}

    # Should have assigned + compulsory routes
    assert assigned_id in rights
    for cid in compulsory_ids:
        assert cid in rights
