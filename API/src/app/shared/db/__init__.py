"""DB plumbing for the new layered app.

For Step 1.4 this module:

1. Re-exports the legacy `engine`, `async_session`, `get_db`, and the
   shared `Base` so new layered code uses the same connection pool and
   metadata as the existing template (one Alembic history, one pool).
2. Registers a SQLAlchemy `after_begin` Session event that sets the
   Postgres session variable `app.org_id` from the active
   `RequestContext` at the start of every transaction. RLS policies
   created via `src.app.shared.rls.apply_rls(...)` read this variable
   and use it to authorise the rows the session can see.

The hook uses `set_config('app.org_id', :v, true)` rather than `SET
LOCAL` so it parametrises cleanly via SQLAlchemy bind params (`true`
makes the change transaction-local, the same scope as `SET LOCAL`). If
no org is present in the request context the hook is a no-op — RLS
policies then see a NULL `app.org_id` and deny all rows.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from src.app.shared.context import get_context
from src.core.db import DATABASE_URL, async_session, engine, get_db
from src.models import Base

__all__ = ["DATABASE_URL", "Base", "async_session", "engine", "get_db"]


@event.listens_for(Session, "after_begin")
def _set_app_org_id(session, transaction, connection) -> None:
    """At the start of each transaction, push `RequestContext.org_id` into Postgres."""
    ctx = get_context()
    if ctx.org_id is None:
        return
    connection.execute(
        text("SELECT set_config('app.org_id', :v, true)"),
        {"v": str(ctx.org_id)},
    )
