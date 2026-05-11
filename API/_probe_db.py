"""One-shot DB probe — uses the app's resolved DATABASE_URL (which handles
any secret-decryption that `config.py` does)."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.db import DATABASE_URL


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        version = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
        print("alembic_version:", version)

        table = (
            await conn.execute(
                text("SELECT to_regclass('custom_field_definitions')")
            )
        ).scalar()
        print("custom_field_definitions table:", table)

        rows = (
            await conn.execute(
                text(
                    "SELECT typname FROM pg_type "
                    "WHERE typname IN ('custom_field_type', 'custom_field_source')"
                )
            )
        ).all()
        print("enum types present:", [r[0] for r in rows])
    await engine.dispose()


asyncio.run(main())
