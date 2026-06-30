import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models import Base
from src.models.routes import Route
from src.providers.route_provider import generate_routes_json
from tests.conftest import TestSession, test_engine


@pytest_asyncio.fixture
async def setup_tables():
    """Create and drop tables for standalone tests (no HTTP client needed)."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
            control_id="logout",
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
@patch("src.services.dev.route_service.async_session", TestSession)
async def test_routes_json_generated_on_startup(setup_tables):
    from config import ROUTES_API

    async with TestSession() as db:
        await _seed_routes(db)
        await db.commit()

    await generate_routes_json()
    assert os.path.exists(ROUTES_API)

    # Clean up
    if os.path.exists(ROUTES_API):
        os.remove(ROUTES_API)


@pytest.mark.asyncio
@patch("src.services.dev.route_service.async_session", TestSession)
async def test_routes_json_contains_all_routes(setup_tables):
    import orjson

    from config import ROUTES_API

    async with TestSession() as db:
        await _seed_routes(db)
        await db.commit()

    await generate_routes_json()

    with open(ROUTES_API, "rb") as f:
        routes_data = orjson.loads(f.read())

    assert "admin_dashboard" in routes_data
    assert "user_dashboard" in routes_data
    assert "logout" in routes_data
    assert len(routes_data) == 3

    if os.path.exists(ROUTES_API):
        os.remove(ROUTES_API)


@pytest.mark.asyncio
@patch("src.services.dev.route_service.async_session", TestSession)
async def test_routes_json_keyed_by_control_id(setup_tables):
    import orjson

    from config import ROUTES_API

    async with TestSession() as db:
        await _seed_routes(db)
        await db.commit()

    await generate_routes_json()

    with open(ROUTES_API, "rb") as f:
        routes_data = orjson.loads(f.read())

    for key, value in routes_data.items():
        assert key == value["control_id"]

    if os.path.exists(ROUTES_API):
        os.remove(ROUTES_API)


@pytest.mark.asyncio
@patch("src.services.dev.route_service.generate_routes_json", new_callable=AsyncMock)
async def test_public_config_endpoint(mock_routes, client):
    import orjson

    from config import ROUTES_API

    # Create a routes.json file for the config endpoint to read
    routes_content = {
        "admin_dashboard": {"id": 1, "control_id": "admin_dashboard", "name": "Dashboard"},
        "user_dashboard": {"id": 2, "control_id": "user_dashboard", "name": "Dashboard"},
    }
    os.makedirs(os.path.dirname(ROUTES_API) or ".", exist_ok=True)
    with open(ROUTES_API, "wb") as f:
        f.write(orjson.dumps(routes_content))

    resp = await client.get("/api/routes/config")
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert "admin_dashboard" in data["data"]
    assert "user_dashboard" in data["data"]

    if os.path.exists(ROUTES_API):
        os.remove(ROUTES_API)
