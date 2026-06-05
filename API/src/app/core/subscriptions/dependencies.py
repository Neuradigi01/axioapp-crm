"""FastAPI dependencies for the subscription / entitlement layer.

`get_entitlements` is the per-request injector that downstream code
(Step 4's `requires_feature` / `enforces_cap` decorators, Step 10's
read-only middleware, Step 7's billing read API) depends on so the
bundle is loaded exactly once per request.

Caching:
  - The `Entitlements` bundle itself is request-scoped — `get_entitlements`
    is a normal FastAPI dependency, so FastAPI memoises its return value
    inside one request's dependency graph.
  - The plan registry under `plans.py` is process-cached at import.
  - The `subscriptions` row is read once via `load_for_org`.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import entitlements as _entitlements
from src.app.core.subscriptions.entitlements import Entitlements
from src.app.core.users.models import User
from src.app.shared.db import get_db


async def get_entitlements(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Entitlements:
    """Load the caller's org's entitlements bundle for the current request.

    Authenticates as a side effect: `get_current_user` raises 401 if the
    request is anonymous. Read-only / archived orgs still resolve their
    bundle here — the `Entitlements.is_read_only` flag is consumed by
    Step 10's middleware and Step 4's decorators to decide whether to
    short-circuit with 402.
    """
    return await _entitlements.load_for_org(db, user.org_id)
