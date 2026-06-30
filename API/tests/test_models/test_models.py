import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.security.password import hash_password
from src.models.admin import Admin
from src.models.user import UserInfo, UserLogin


@pytest.mark.asyncio
async def test_create_user_login(test_db):
    db = test_db
    user = UserLogin(
        user_id="new_user",
        password=hash_password("password123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    stmt = select(UserLogin).where(UserLogin.user_id == "new_user")
    result = await db.execute(stmt)
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.user_id == "new_user"
    assert fetched.is_active is True


@pytest.mark.asyncio
async def test_create_admin(test_db):
    db = test_db
    admin = Admin(
        admin_user_id="new_admin",
        password=hash_password("admin123"),
        name="New Admin",
        email="newadmin@test.com",
        is_super_admin=False,
        is_active=True,
    )
    db.add(admin)
    await db.flush()

    stmt = select(Admin).where(Admin.admin_user_id == "new_admin")
    result = await db.execute(stmt)
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.admin_user_id == "new_admin"
    assert fetched.is_super_admin is False


@pytest.mark.asyncio
async def test_user_info_relationship(test_db):
    db = test_db

    user_login = UserLogin(
        user_id="rel_user",
        password=hash_password("password123"),
    )
    db.add(user_login)
    await db.flush()

    user_info = UserInfo(
        member_id=user_login.id,
        first_name="Relation",
        last_name="Test",
        email="relation@test.com",
    )
    db.add(user_info)
    await db.flush()

    from sqlalchemy.orm import selectinload

    stmt = (
        select(UserLogin)
        .options(selectinload(UserLogin.user_info))
        .where(UserLogin.user_id == "rel_user")
    )
    result = await db.execute(stmt)
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.user_info is not None
    assert fetched.user_info.first_name == "Relation"


@pytest.mark.asyncio
async def test_unique_user_id(test_db):
    db = test_db

    user1 = UserLogin(user_id="duplicate_user", password=hash_password("pass1"))
    db.add(user1)
    await db.flush()

    user2 = UserLogin(user_id="duplicate_user", password=hash_password("pass2"))
    db.add(user2)

    with pytest.raises(IntegrityError):
        await db.flush()

    await db.rollback()


@pytest.mark.asyncio
async def test_unique_email(test_db):
    db = test_db

    user1 = UserLogin(user_id="email_user1", password=hash_password("pass1"))
    db.add(user1)
    await db.flush()

    info1 = UserInfo(
        member_id=user1.id,
        first_name="First",
        last_name="User",
        email="duplicate@test.com",
    )
    db.add(info1)
    await db.flush()

    user2 = UserLogin(user_id="email_user2", password=hash_password("pass2"))
    db.add(user2)
    await db.flush()

    info2 = UserInfo(
        member_id=user2.id,
        first_name="Second",
        last_name="User",
        email="duplicate@test.com",
    )
    db.add(info2)

    with pytest.raises(IntegrityError):
        await db.flush()

    await db.rollback()
