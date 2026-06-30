"""Entitlement service — the single arbiter of "what is this org allowed to do?"

Every gated endpoint (Step 4's decorators, Step 10's read-only middleware)
funnels through this module. It composes Step 1's plan registry with
Step 2's `subscriptions` row to answer two questions per request:

  1. **Feature gate** — "Does the org's plan grant `<feature_key>`?"
  2. **Cap gate**     — "Adding one more `<resource>`, does the org
                          stay under the plan's cap?"

Status semantics:

| Status       | `is_read_only` | Effect on `require_*`                       |
|--------------|----------------|---------------------------------------------|
| `trialing`   | False          | normal (trial mirrors Basic per founder)    |
| `active`     | False          | normal                                      |
| `past_due`   | True           | every `require_*` raises read_only          |
| `read_only`  | True           | every `require_*` raises read_only          |
| `archived`   | True           | every `require_*` raises read_only          |
| `cancelled`  | True           | every `require_*` raises read_only          |

Read-only short-circuit happens BEFORE the feature/cap check so the
caller gets the most actionable 402 (`reason='read_only'`) when the
subscription itself is blocked.

Caching is per-request: the `get_entitlements` FastAPI dependency
(see `dependencies.py`) materialises the `Entitlements` once and
passes it into the handler. Multiple `require_*` calls inside the
same handler reuse the same instance — no extra DB hits.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions import plans
from src.app.core.subscriptions.exceptions import EntitlementError
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.plans import KNOWN_FEATURE_KEYS, Cap, Plan
from src.app.core.subscriptions.service import get_active_subscription

log = logging.getLogger(__name__)


_READ_ONLY_STATUSES = frozenset({"past_due", "read_only", "archived", "cancelled"})


@dataclass(frozen=True, slots=True)
class Entitlements:
    """A frozen snapshot of one org's plan + subscription for the duration of a request."""

    org_id: uuid.UUID
    subscription: Subscription
    plan: Plan

    @property
    def plan_code(self) -> str:
        return self.plan.code

    @property
    def status(self) -> str:
        return self.subscription.status

    @property
    def is_read_only(self) -> bool:
        return self.status in _READ_ONLY_STATUSES

    @property
    def seats_purchased(self) -> int:
        return self.subscription.seats_purchased

    # ----- Feature checks ----------------------------------------------------

    def has_feature(self, key: str) -> bool:
        """True if the plan grants `key`. Unknown keys log a warning and return False."""
        if key not in KNOWN_FEATURE_KEYS:
            log.warning("entitlement check for unknown feature key %r", key)
            return False
        return self.plan.features.has(key)

    # ----- Cap checks --------------------------------------------------------

    def cap_for(self, resource: str) -> int:
        """The plan's cap for `resource`. Returns -1 for unlimited.

        Unknown resources raise — caps come from a fixed taxonomy in
        `plans.yaml`, so a typo is a developer bug, not a data error.
        """
        caps = self.plan.caps
        try:
            return getattr(caps, resource)
        except AttributeError as exc:
            raise KeyError(f"unknown cap resource: {resource!r}") from exc

    def is_within_cap(self, resource: str, current: int) -> bool:
        """Would `current + 1` still fit under the plan's cap for `resource`?

        Unlimited (`cap == -1`) always returns True.
        """
        cap = self.cap_for(resource)
        if Cap.is_unlimited(cap):
            return True
        return (current + 1) <= cap


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


async def load_for_org(session: AsyncSession, org_id: uuid.UUID) -> Entitlements:
    """Materialise the entitlements bundle for `org_id`.

    Raises `EntitlementError("read_only")` if the org has no active
    subscription at all — that should not happen post Step 2 backfill,
    but guards against orphan organizations that snuck in during DB
    surgery.

    Raises `RuntimeError` if the subscription's `plan_code` is not in
    the plan registry — a stale row with a removed plan. Surfacing this
    loudly forces the operator to migrate the row before traffic resumes.
    """
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise EntitlementError(
            "read_only",
            message="No active subscription for this organization.",
        )
    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(
            f"unknown plan_code {sub.plan_code!r} on subscription {sub.id} "
            f"for org {org_id} — registry drift"
        )
    return Entitlements(org_id=org_id, subscription=sub, plan=plan)


# ---------------------------------------------------------------------------
# Imperative checks — call from service layer / decorators
# ---------------------------------------------------------------------------


async def require_feature(session: AsyncSession, org_id: uuid.UUID, feature_key: str) -> None:
    """Raise 402 if the org's plan does not grant `feature_key`.

    Read-only / past_due / archived / cancelled subscriptions raise
    `EntitlementError("read_only")` BEFORE the feature check — they
    can't take any write action regardless of plan grants.
    """
    ent = await load_for_org(session, org_id)
    _require_writeable(ent)
    if ent.has_feature(feature_key):
        return
    required = _lowest_plan_granting_feature(feature_key)
    raise EntitlementError(
        "feature_locked",
        required_plan=required,
        message=(
            f"This feature requires the {required.title()} plan or higher."
            if required
            else "This feature is not available on any plan."
        ),
    )


async def require_capacity(
    session: AsyncSession, org_id: uuid.UUID, resource: str, current: int
) -> None:
    """Raise 402 if adding one more `<resource>` would exceed the plan's cap.

    Pass `current = N - 1` to gate the Nth write. Unlimited caps never raise.
    Read-only subscriptions raise `EntitlementError("read_only")` first.
    """
    ent = await load_for_org(session, org_id)
    _require_writeable(ent)
    if ent.is_within_cap(resource, current):
        return
    cap = ent.cap_for(resource)
    required = _lowest_plan_with_higher_cap(resource, current_cap=cap)
    raise EntitlementError(
        "cap_reached",
        required_plan=required,
        resource=resource,
        cap=cap,
        message=(f"You have reached the {resource} limit on your current plan."),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_writeable(ent: Entitlements) -> None:
    """Raise `read_only` (or `trial_expired`) if the subscription status forbids writes.

    `trial_expired` is emitted when a trial transitioned to read-only without
    ever being upgraded (`status='read_only' AND plan_code='trial'`). Every
    other read-only-equivalent state (paid → past_due → read_only, archived,
    cancelled) surfaces as plain `read_only` so the frontend distinguishes
    "you never paid — upgrade now" from "your card failed — fix your payment".
    """
    if not ent.is_read_only:
        return
    reason = (
        "trial_expired" if ent.status == "read_only" and ent.plan_code == "trial" else "read_only"
    )
    raise EntitlementError(reason)


def _lowest_plan_granting_feature(feature_key: str) -> str | None:
    """Return the code of the cheapest *purchasable* plan that grants `feature_key`.

    Trial is skipped — it is not an upgrade target. Plans are scanned
    in `display_order` ascending, so the first match is the cheapest.
    """
    for plan in plans.all():
        if plan.code == "trial":
            continue
        if plan.features.has(feature_key):
            return plan.code
    return None


def _lowest_plan_with_higher_cap(resource: str, *, current_cap: int) -> str | None:
    """Return the cheapest purchasable plan whose `<resource>` cap is strictly higher
    than `current_cap`, or unlimited.

    Used to populate `required_plan` on `cap_reached` errors so the
    frontend can suggest the right upgrade target.
    """
    for plan in plans.all():
        if plan.code == "trial":
            continue
        try:
            other = getattr(plan.caps, resource)
        except AttributeError:
            continue
        if Cap.is_unlimited(other):
            return plan.code
        if not Cap.is_unlimited(current_cap) and other > current_cap:
            return plan.code
    return None
