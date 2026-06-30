import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from src.core.db import DATABASE_URL
from src.core.security.jwt import create_access_token
from src.core.security.password import hash_password
from src.models import Base
from src.models.admin import Admin
from src.models.routes import Route
from src.models.user import UserInfo, UserLogin

# Use a separate test database
TEST_DB_NAME = f"{DB_NAME}_test"
TEST_DATABASE_URL = DATABASE_URL.replace(f"/{DB_NAME}", f"/{TEST_DB_NAME}")

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _ensure_test_db_exists():
    """Create the test database if it doesn't exist."""
    sys_conn = await asyncpg.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
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


async def _ensure_test_db_extensions():
    """Install Postgres extensions the layered models depend on (citext, pgcrypto).

    Idempotent. Runs once per test session against the test DB so
    `Base.metadata.create_all` can construct tables that reference
    these types/functions (e.g. `users.email CITEXT`,
    `id UUID DEFAULT gen_random_uuid()`).
    """
    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def ensure_test_db():
    """Auto-create the test database and install required extensions."""
    await _ensure_test_db_exists()
    await _ensure_test_db_extensions()


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
    return create_access_token(
        {
            "user_id": data["admin"].admin_user_id,
            "role": "Admin",
            "admin_id": data["admin"].id,
            "access_rights": "1,2",
        }
    )


@pytest_asyncio.fixture
async def user_token(seed_test_data):
    data = seed_test_data
    return create_access_token(
        {
            "user_id": data["user_login"].user_id,
            "role": "User",
            "member_id": data["user_login"].id,
            "access_rights": "2",
        }
    )


def _patch_all_async_sessions():
    """Patch async_session in all modules that import it directly from src.core.db."""
    import src.core.db as db_module
    import src.core.security.jwt as jwt_module
    import src.providers.error_log_provider as error_log_module
    import src.providers.route_provider as route_provider_module

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


# --- Layered FurnitureCRM app fixtures --------------------------------------


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    """Wipe the in-memory login rate-limit bucket between every test.

    Without this, an earlier test that hammered `/auth/login` could push
    a later test into 429s. The rate-limit test resets explicitly too.
    """
    from src.app.shared.rate_limit import login_limiter

    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest_asyncio.fixture
async def layered_client():
    """AsyncClient wrapped around the layered FurnitureCRM ASGI app."""
    from src.app.main import app

    originals = _patch_all_async_sessions()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    _restore_all_async_sessions(originals)


@pytest_asyncio.fixture
async def seeded_admin():
    """One org + admin role + admin user. Password is `Admin@123`.

    Builds the post-DR.7 three-table user layout (`tbl_user_login` +
    `tbl_user_info` + `tbl_organization_members`):
      - `Organization` (UUID id, unique slug per test) — TenantScoped parent.
      - `Role` (UUID id, scoped to the org, name='admin', is_system=true).
      - `tbl_user_login` (BigInteger id, legacy_uuid UUID, password, is_active).
        Uses the legacy `UserLogin` class for INSERT because the layered
        `User` mapper excludes the legacy `user_id` text login-handle (NOT
        NULL on the table). `legacy_uuid` is set with a raw UPDATE because
        the legacy class doesn't map it.
      - `tbl_user_info` (member_id → tbl_user_login.id, first_name, email).
      - `tbl_organization_members` (org_id, user_member_id, role_id,
        is_active=true, status='active').

    Returns dict keyed by `org`, `role`, `user` (layered `User` instance with
    selectin relationships populated → `.email`, `.org_id`, `.role_id`
    properties resolve correctly), `password` (plaintext).
    """
    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy import text as sql_text

    from src.app.core.permissions.models import Role
    from src.app.core.tenants.models import Organization
    from src.app.core.users.models import OrganizationMember, User
    from src.app.shared.security.password import hash_password as _hp
    from src.models.user import UserInfo as LegacyUserInfo
    from src.models.user import UserLogin

    org_uuid = _uuid.uuid4()
    role_uuid = _uuid.uuid4()
    user_uuid = _uuid.uuid4()
    slug = f"demo-{_uuid.uuid4().hex[:6]}"
    login_handle = f"test-{_uuid.uuid4().hex[:8]}"

    org = Organization(id=org_uuid, name="Demo", slug=slug)
    role = Role(id=role_uuid, org_id=org_uuid, name="admin", is_system=True)
    user_login = UserLogin(
        user_id=login_handle,
        password=_hp("Admin@123"),
        is_active=True,
    )

    async with TestSession() as session:
        session.add(org)
        await session.flush()
        session.add(role)
        await session.flush()

        session.add(user_login)
        await session.flush()  # populates user_login.id (bigint)

        # `legacy_uuid` lives on `tbl_user_login` (DR.6.1) but the legacy
        # mapper doesn't include it. Set via raw UPDATE.
        await session.execute(
            sql_text("UPDATE tbl_user_login SET legacy_uuid = :uuid WHERE id = :id"),
            {"uuid": str(user_uuid), "id": user_login.id},
        )

        # The `users` shim Table (UUID id PK) is what every cross-table
        # `user_id UUID` FK in the codebase still references — auth_sessions,
        # audit_logs, staff_sessions, demo_credentials. In production the
        # DR.6 migrations populated `users(id)` for the existing user set
        # and ongoing flows mirror new logins into it; in a fresh test DB
        # the shim is empty so any post-login flow (e.g. AuthSession insert)
        # FK-violates. Insert the mirror row here.
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:uuid) ON CONFLICT DO NOTHING"),
            {"uuid": str(user_uuid)},
        )

        session.add(
            LegacyUserInfo(
                member_id=user_login.id,
                first_name="Admin",
                last_name="User",
                email="admin@demo.local",
                mobile_no="0000000000",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_uuid,
                user_member_id=user_login.id,
                role_id=role_uuid,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()

        # Re-fetch the layered `User` so `.info` and `.memberships` populate
        # via selectin. Tests rely on the @property aliases (.email, .org_id,
        # .role_id) which read off those relationships.
        result = await session.execute(select(User).where(User.id == user_login.id))
        user = result.scalar_one()

    return {"org": org, "role": role, "user": user, "password": "Admin@123"}
