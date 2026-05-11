from sqlalchemy import select, func
from src.core.db import async_session
from src.models.admin import Admin
from src.core.security.password import hash_password


async def _seed_admin(
    admin_user_id: str,
    password: str,
    name: str,
    email: str,
    is_super_admin: bool,
    is_developer: bool,
):
    async with async_session() as db:
        existing = (await db.execute(
            select(Admin).where(func.lower(Admin.admin_user_id) == admin_user_id.lower())
        )).scalar_one_or_none()
        if existing:
            print(f"Admin '{admin_user_id}' already exists, skipping.")
            return

        admin = Admin(
            admin_user_id=admin_user_id,
            password=hash_password(password),
            name=name,
            email=email,
            is_super_admin=is_super_admin,
            is_developer=is_developer,
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        print(f"Admin '{admin_user_id}' seeded successfully.")


async def seed_super_admin():
    await _seed_admin(
        admin_user_id="DevAdmin",
        password="admin123",
        name="Developer Admin",
        email="devadmin@neuradigi.com",
        is_super_admin=True,
        is_developer=True,
    )
    await _seed_admin(
        admin_user_id="admin",
        password="admin123",
        name="Super Admin",
        email="admin@example.com",
        is_super_admin=True,
        is_developer=False,
    )
