import os
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Celery workers wrap each task in ``asyncio.run(...)`` which spins up a
# fresh event loop per task. Connections cached in SQLAlchemy's pool from
# a previous task's loop are bound to that dead loop's selectors and fail
# on the next task with either ``InterfaceError: cannot perform operation:
# another operation is in progress`` (asyncpg state) or ``RuntimeError:
# ... got Future ... attached to a different loop`` (asyncio binding).
# NullPool sidesteps both: each session opens a fresh connection (~2-5ms
# per session) and never caches it, so cross-loop reuse is impossible.
# FastAPI processes keep the cached pool — they reuse a single event loop.
_USE_NULL_POOL = os.getenv("DB_NULL_POOL", "").lower() in ("1", "true", "yes")

if _USE_NULL_POOL:
    engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)
else:
    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=20, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
