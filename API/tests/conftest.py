import pytest
import pytest_asyncio
import asyncpg
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
from src.models.routes import Route
from src.core.security.password import hash_password
from src.core.security.jwt import create_access_token
from src.core.db import DATABASE_URL
from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

# Use a separate test database
TEST_DB_NAME = f"{DB_NAME}_test"
TEST_DATABASE_URL = DATABASE_URL.replace(f"/{DB_NAME}", f"/{TEST_DB_NAME}")

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _ensure_test_db_exists():
    """Create the test database if it doesn't exist."""
    sys_conn = await asyncpg.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWORD,
        database="postgres",
    )
    try:
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await sys_conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await sys_conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def ensure_test_db():
    """Auto-create the test database before any tests run."""
    await _ensure_test_db_exists()


@pytest_asyncio.fixture(scope="function")
async def test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def seed_test_data(test_db):
    db = test_db

    # Create test admin
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

    # Create test user
    user_login = UserLogin(
        user_id="test_user",
        password=hash_password("user123"),
        is_active=True,
    )
    db.add(user_login)
    await db.flush()

    user_info = UserInfo(
        member_id=user_login.id,
        first_name="Test",
        last_name="User",
        email="user@test.com",
        mobile_no="1234567890",
    )
    db.add(user_info)

    # Create test routes
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
            order_no=1,
            is_compulsory=True,
        ),
    ]
    db.add_all(routes)
    await db.commit()

    return {"admin": admin, "user_login": user_login, "user_info": user_info, "routes": routes}


@pytest_asyncio.fixture
async def admin_token(seed_test_data):
    data = seed_test_data
    return create_access_token({
        "user_id": data["admin"].admin_user_id,
        "role": "Admin",
        "admin_id": data["admin"].id,
        "access_rights": "1,2",
    })


@pytest_asyncio.fixture
async def user_token(seed_test_data):
    data = seed_test_data
    return create_access_token({
        "user_id": data["user_login"].user_id,
        "role": "User",
        "member_id": data["user_login"].id,
        "access_rights": "2",
    })


def _patch_all_async_sessions():
    """Patch async_session in all modules that import it directly from src.core.db."""
    import src.core.db as db_module
    import src.providers.route_provider as route_provider_module
    import src.providers.error_log_provider as error_log_module
    import src.core.security.jwt as jwt_module

    modules = [db_module, route_provider_module, error_log_module, jwt_module]
    originals = {mod: mod.async_session for mod in modules}
    for mod in modules:
        mod.async_session = TestSession
    return originals


def _restore_all_async_sessions(originals):
    for mod, original in originals.items():
        mod.async_session = original


@pytest_asyncio.fixture
async def test_client():
    from main import app

    originals = _patch_all_async_sessions()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    _restore_all_async_sessions(originals)
