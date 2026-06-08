"""FastAPI dependencies for the subscription / entitlement / payment layer.

Three injectors live here:

  - `get_entitlements` (Step 3 / 7) — per-request plan + subscription
    bundle, consumed by the decorators and the read-only middleware.
  - `get_payment_provider` (Step 11) — process-wide singleton for the
    Stripe SDK adapter; Steps 12 (Checkout) and 13 (webhooks) inject
    this rather than constructing `StripeProvider` themselves.

Caching:
  - The `Entitlements` bundle is request-scoped — FastAPI memoises the
    dependency once per request graph.
  - The plan registry under `plans.py` is process-cached at import.
  - The Stripe provider is process-cached via `@lru_cache` so the YAML
    price map is read once at boot, not per request.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import entitlements as _entitlements
from src.app.core.subscriptions.entitlements import Entitlements
from src.app.core.subscriptions.payment_provider import PaymentProvider
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


@lru_cache(maxsize=1)
def get_payment_provider() -> PaymentProvider | None:
    """Process-wide singleton `PaymentProvider` instance, or `None`.

    Constructed lazily on first injection so the Stripe price-map YAML
    read does not run at import time. Cached so re-injection is free.

    Returns `None` when `STRIPE_SECRET_KEY` is unset, so unrelated
    test environments (and the pre-Step-11 dev workflow) can run the
    plan-change / seat-change endpoints without a Stripe account. The
    route handlers treat `None` as "no augmentation" and emit the
    stub `checkout_url=null` response that Steps 8 / 9 originally
    shipped.
    """
    # Local imports keep `config` and the Stripe adapter out of the
    # module's top-level dependency graph — the entitlement service
    # path does not touch them.
    from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
    from src.app.core.subscriptions.providers.stripe_provider import (
        StripeProvider,
    )

    if not STRIPE_SECRET_KEY:
        return None
    return StripeProvider(
        secret_key=STRIPE_SECRET_KEY,
        webhook_secret=STRIPE_WEBHOOK_SECRET or "",
    )
