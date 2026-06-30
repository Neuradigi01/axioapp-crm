import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

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
    # NullPool + pool_pre_ping evicts broken sockets cleanly per session.
    # The "pool_pre_ping" here is a no-op for NullPool (no pool to ping)
    # but is set so future moves between Null/Queue pools keep the
    # liveness check.
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
else:
    # Tightened from 20+10 (=30 caps) to 10+5 (=15 caps) after the
    # 2026-06-30 ``TooManyConnectionsError`` incident: remote Postgres
    # ships with ``max_connections=100`` and the api + worker + beat +
    # flower processes were jointly exceeding the budget. Pool-pre-
    # ping evicts connections the DB has dropped (asyncpg "connection
    # was closed in the middle of operation" race); recycle bounces
    # any pooled connection older than 15 minutes so stale sockets
    # never resurrect.
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=900,
    )
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session
