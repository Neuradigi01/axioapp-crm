"""Hook called inside the new-org transaction to seed a trial subscription.

Every new org created via self-signup gets a 14-day trial. The handler
in `core/auth/service.py` (both `register_with_new_org` and
`register_user_only`) calls `create_trial_subscription` AFTER the
organization is inserted but BEFORE the parent transaction commits.

If anything later in the signup flow fails, the trial row rolls back
with the rest of the bootstrap — there is no codepath that produces an
organization without a subscription. The lifecycle service (Step 6's
`lifecycle.py`) only ever sees orgs in known states.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import Subscription


# Length of the free trial granted to every new org. Mirrored in
# `plans.yaml` (`trial.trial_duration_days = 14`) — keep in sync if one
# changes.
TRIAL_DURATION = timedelta(days=14)

# Seats allocated to a trial. Matches `trial.pricing.included_seats` in
# `plans.yaml`. Trial seats are not purchasable separately — to add
# more, the org must upgrade to a paid plan first.
TRIAL_SEATS = 3


async def create_trial_subscription(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> Subscription:
    """Insert a fresh trial subscription for `org_id`. Does NOT commit.

    The parent transaction (the register handler) commits the row along
    with the organization, Owner role, and OrganizationMember inserts.
    Failure here propagates and rolls the whole signup back.

    Idempotency is not handled here — the partial unique index on
    `(org_id) WHERE status IN (active set)` will already reject a
    second active subscription for the same org. Callers should only
    invoke this on a fresh org.
    """
    now = datetime.now(tz=timezone.utc)
    trial_end = now + TRIAL_DURATION
    sub = Subscription(
        org_id=org_id,
        plan_code="trial",
        status="trialing",
        billing_cycle="monthly",
        seats_purchased=TRIAL_SEATS,
        trial_started_at=now,
        trial_ends_at=trial_end,
        current_period_start=now,
        current_period_end=trial_end,
    )
    session.add(sub)

    # Step 19 — audit-log the trial creation. `audit.log` opens its
    # own session, so if the parent signup transaction rolls back the
    # subscription row, the audit row may be orphaned (org_id pointing
    # at a no-longer-existent org). That is the documented best-effort
    # contract — append-only history beats coupling the lifecycle of
    # a status event to the lifecycle of the entity.
    await audit.log(
        "subscription.created",
        org_id=org_id,
        entity_type="subscription",
        after={
            "plan_code": "trial",
            "status": "trialing",
            "seats_purchased": TRIAL_SEATS,
            "trial_ends_at": trial_end.isoformat(),
        },
        user_id=None,  # signup is a system action
    )
    return sub
