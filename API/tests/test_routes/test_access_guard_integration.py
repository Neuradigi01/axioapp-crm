import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from fastapi import APIRouter, Depends
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.routes import Route
from src.core.security.jwt import get_current_user, create_access_token
from src.core.security.access_guard import AccessGuard
from tests.conftest import test_engine, TestSession

# Create a temporary test router with a protected endpoint
_test_router = APIRouter(prefix="/api/test-guard")


@_test_router.get("/protected")
async def protected_endpoint(payload: dict = Depends(AccessGuard([100]))):
    return {"success": True, "message": "Access granted", "user_id": payload["user_id"]}


@pytest_asyncio.fixture
async def client():
    from main import app
    import src.core.db as db_module

    # Add our test router temporarily
    app.include_router(_test_router)

    original_session = db_module.async_session
    db_module.async_session = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    db_module.async_session = original_session

    # Remove the test router
    app.routes[:] = [r for r in app.routes if not (hasattr(r, 'path') and '/test-guard' in str(getattr(r, 'path', '')))]


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_protected_endpoint_without_token(mock_routes, client):
    resp = await client.get("/api/test-guard/protected")
    assert resp.status_code == 401 or resp.status_code == 403


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_protected_endpoint_with_valid_token(mock_routes, client):
    token = create_access_token({
        "user_id": "test_user",
        "role": "User",
        "member_id": 1,
        "access_rights": "100",  # Has route 100 which is required
    })
    resp = await client.get("/api/test-guard/protected", headers={
        "Authorization": f"Bearer {token}"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["user_id"] == "test_user"


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_protected_endpoint_without_required_right(mock_routes, client):
    token = create_access_token({
        "user_id": "test_user",
        "role": "User",
        "member_id": 1,
        "access_rights": "1,2,3",  # Does NOT have route 100
    })
    resp = await client.get("/api/test-guard/protected", headers={
        "Authorization": f"Bearer {token}"
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_protected_endpoint_with_required_right(mock_routes, client):
    token = create_access_token({
        "user_id": "admin_user",
        "role": "Admin",
        "admin_id": 1,
        "access_rights": "1,50,100",  # Has route 100
    })
    resp = await client.get("/api/test-guard/protected", headers={
        "Authorization": f"Bearer {token}"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["user_id"] == "admin_user"
