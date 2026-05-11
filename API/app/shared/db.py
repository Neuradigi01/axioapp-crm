"""Re-export of the existing legacy DB plumbing.

The legacy `src/core/db.py` already provides the async engine and session,
and the legacy `src/models/__init__.py` defines `Base = DeclarativeBase()`
with all existing models pre-registered.

For now we share that single Base + engine across legacy and new code so:
  - There is one Postgres connection pool.
  - There is one Alembic migration history.
  - New FurnitureCRM models inherit from the same Base and show up in autogenerate.

Later (Steps 1.5/1.6 and beyond), the legacy `src.*` paths will be retired and
this module will own its own engine/Base. For Step 1.3 it's a thin proxy.
"""
from src.core.db import DATABASE_URL, async_session, engine, get_db
from src.models import Base

__all__ = ["DATABASE_URL", "Base", "async_session", "engine", "get_db"]
