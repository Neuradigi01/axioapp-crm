"""Trial-and-archive state machine for subscriptions.

Three transitions, one reminder:

  trialing  → read_only   (when now > trial_ends_at)
  read_only → archived    (when now > read_only_at + 30 days)
  archived  → row deleted (when now > archived_at + 90 days)

  trial_ending_soon email — fires once, when trial_ends_at is within
  the next 3 days and `reminders_sent['trial_ending_soon']` is unset.

`transition_if_due` is idempotent and race-safe: it uses a conditional
`UPDATE ... WHERE id = ? AND status = <expected>` so a concurrent
plan-change-to-active or webhook-driven upgrade aborts the transition
cleanly without raising.

Audit events use `user_id=None` to denote a system actor; the audit
service stores nullable `user_id` (see `core/audit/models.py:31`) and
the convention across this codebase is "absent user => system."

The Celery task `advance_trial_lifecycle` in `tasks.py` calls
`scan_and_transition_due` + `fire_due_reminders` once per hour.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import ACTIVE_STATUSES, Subscription
from src.app.core.subscriptions.notifications import send_billing_email

log = logging.getLogger(__name__)


# How long an org may stay in each end-of-life state. The product spec
# (track README) defines the trial → read_only → archived → delete
# cadence; the values here are the source of truth for the lifecycle.
READ_ONLY_TO_ARCHIVED = timedelta(days=30)
ARCHIVED_TO_DELETED = timedelta(days=90)

# How early to send the "trial ending in N days" reminder.
TRIAL_REMINDER_LEAD = timedelta(days=3)

# Cycle lengths used when projecting a fresh period after applying a
# scheduled plan change. Mirrors `tasks._CYCLE_LENGTHS` but kept local
# so the lifecycle module has no upward dependency on Celery code.
_CYCLE_LENGTHS: dict[str, timedelta] = {
    "monthly": timedelta(days=30),
    "annual": timedelta(days=365),
}


# ---------------------------------------------------------------------------
# Single-row transition
# ---------------------------------------------------------------------------

async def transition_if_due(
    session: AsyncSession, subscription: Subscription
) -> str | None:
    """Apply the appropriate transition if `subscription` is past its
    deadline. Returns the new status or None.

    All writes use a conditional `UPDATE ... WHERE id = :id AND status
    = :expected` so a concurrent payment-to-active flip aborts the
    transition silently. Audit events and emails fire only when the
    `UPDATE` actually changed a row.
    """
    now = datetime.now(tz=timezone.utc)

    if (
        subscription.status == "trialing"
        and subscription.trial_ends_at is not None
        and now > subscription.trial_ends_at
    ):
        return await _transition(
            session,
            subscription,
            from_status="trialing",
            to_status="read_only",
            set_sql="status = 'read_only', read_only_at = now()",
            audit_action="trial.expired",
            email_key="trial_expired",
        )

    if (
        subscription.status == "read_only"
        and subscription.read_only_at is not None
        and now > subscription.read_only_at + READ_ONLY_TO_ARCHIVED
    ):
        return await _transition(
            session,
            subscription,
            from_status="read_only",
            to_status="archived",
            set_sql="status = 'archived', archived_at = now()",
            audit_action="subscription.archived",
            email_key="subscription_archived",
        )

    if (
        subscription.status == "archived"
        and subscription.archived_at is not None
        and now > subscription.archived_at + ARCHIVED_TO_DELETED
    ):
        return await _delete_archived(session, subscription)

    return None


async def _transition(
    session: AsyncSession,
    subscription: Subscription,
    *,
    from_status: str,
    to_status: str,
    set_sql: str,
    audit_action: str,
    email_key: str,
) -> str | None:
    """Run the conditional UPDATE; emit side effects only on a real change."""
    result = await session.execute(
        text(
            f"UPDATE subscriptions SET {set_sql} "
            "WHERE id = :id AND status = :from_status"
        ),
        {"id": subscription.id, "from_status": from_status},
    )
    if (result.rowcount or 0) == 0:
        # Lost the race — concurrent upgrade beat us to it. No event,
        # no email. The next scan will skip the row since status no
        # longer matches.
        return None

    await audit.log(
        audit_action,
        org_id=subscription.org_id,
        entity_type="subscription",
        entity_id=subscription.id,
        after={"from_status": from_status, "to_status": to_status},
        user_id=None,  # system actor
    )
    await send_billing_email(
        org_id=subscription.org_id,
        template_key=email_key,  # type: ignore[arg-type]
        context={"subscription_id": str(subscription.id)},
    )
    return to_status


async def _delete_archived(
    session: AsyncSession, subscription: Subscription
) -> str | None:
    """Drop the archived subscription row entirely and emit org.deleted.

    Conditional on status='archived' so a concurrent operator-driven
    restore (manual reactivation) aborts the delete.
    """
    result = await session.execute(
        text(
            "DELETE FROM subscriptions WHERE id = :id AND status = 'archived'"
        ),
        {"id": subscription.id},
    )
    if (result.rowcount or 0) == 0:
        return None
    await audit.log(
        "org.deleted",
        org_id=subscription.org_id,
        entity_type="subscription",
        entity_id=subscription.id,
        user_id=None,
    )
    # No email — the org has been on read-only then archived for 120
    # days at this point. They have churned.
    return "deleted"


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

async def scan_and_transition_due(session: AsyncSession) -> dict[str, int]:
    """Walk every subscription that might be due for transition.

    Two passes per call:
      1. End-of-life advances — trial → read_only → archived → delete.
      2. Scheduled-change applications — flip `plan_code` /
         `billing_cycle` / `seats_purchased` from the `next_*` columns
         at period boundary (Step 8).

    Beat task has no tenant context, so the auto-org-filter listener
    is a no-op and this scan sees every org's row.

    Returns a counted summary for the Celery task to log.
    """
    summary = {
        "trialing_to_read_only": 0,
        "read_only_to_archived": 0,
        "archived_to_deleted": 0,
        "skipped_due_to_race": 0,
        "scheduled_change_applied": 0,
        "scheduled_change_skipped_due_to_race": 0,
    }
    now = datetime.now(tz=timezone.utc)

    rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.status.in_(("trialing", "read_only", "archived"))
            )
        )
    ).scalars().all()

    for sub in rows:
        # Cheap pre-check so we don't issue a no-op UPDATE for every
        # row in the table.
        if not _is_due(sub, now):
            continue
        new_status = await transition_if_due(session, sub)
        if new_status is None:
            summary["skipped_due_to_race"] += 1
            continue
        if new_status == "read_only":
            summary["trialing_to_read_only"] += 1
        elif new_status == "archived":
            summary["read_only_to_archived"] += 1
        elif new_status == "deleted":
            summary["archived_to_deleted"] += 1

    # Scheduled-change pass — every active sub with a parked `next_*`
    # row whose period just ended. The filter is the same shape as the
    # row-level conditional UPDATE inside `apply_scheduled_change_if_due`
    # so the cheap-prefilter is also a correctness statement.
    pending = (
        await session.execute(
            select(Subscription).where(
                Subscription.next_plan_code.is_not(None),
                Subscription.current_period_end <= now,
                Subscription.status.in_(ACTIVE_STATUSES),
            )
        )
    ).scalars().all()

    for sub in pending:
        applied = await apply_scheduled_change_if_due(session, sub)
        if applied is None:
            summary["scheduled_change_skipped_due_to_race"] += 1
        else:
            summary["scheduled_change_applied"] += 1

    return summary


def _is_due(sub: Subscription, now: datetime) -> bool:
    if sub.status == "trialing":
        return sub.trial_ends_at is not None and now > sub.trial_ends_at
    if sub.status == "read_only":
        return (
            sub.read_only_at is not None
            and now > sub.read_only_at + READ_ONLY_TO_ARCHIVED
        )
    if sub.status == "archived":
        return (
            sub.archived_at is not None
            and now > sub.archived_at + ARCHIVED_TO_DELETED
        )
    return False


# ---------------------------------------------------------------------------
# Scheduled-change application (Step 8)
# ---------------------------------------------------------------------------


async def apply_scheduled_change_if_due(
    session: AsyncSession, sub: Subscription
) -> dict[str, str] | None:
    """Flip the live plan / cycle / seats from the `next_*` columns
    when the current period has ended.

    Returns a small summary dict on success; `None` if there was
    nothing to apply or the conditional UPDATE lost a race (a
    concurrent operator-driven plan change cleared `next_*` first).

    Race-safety: the UPDATE conditions on `next_plan_code IS NOT NULL`
    AND `current_period_end <= now()` AND the original status — so a
    concurrent change_plan call that overwrote `next_*` (rescheduling)
    or a webhook flip to `cancelled` aborts this transition silently.

    Catch-up: if multiple period boundaries have elapsed (beat
    outage), the period is advanced past every elapsed window so the
    counter-rollover task does not need to re-rollover.
    """
    now = datetime.now(tz=timezone.utc)
    if sub.next_plan_code is None or sub.current_period_end > now:
        return None
    if sub.status not in ACTIVE_STATUSES:
        return None

    new_cycle = sub.next_billing_cycle or sub.billing_cycle
    cycle_length = _CYCLE_LENGTHS.get(new_cycle)
    if cycle_length is None:
        log.warning(
            "scheduled-change on subscription %s has unknown cycle %r",
            sub.id, new_cycle,
        )
        return None

    new_start = sub.current_period_end
    new_end = new_start + cycle_length
    while new_end <= now:
        new_start = new_end
        new_end = new_start + cycle_length

    new_seats = sub.next_seats if sub.next_seats is not None else sub.seats_purchased

    result = await session.execute(
        text(
            """
            UPDATE subscriptions
            SET
                plan_code = :plan_code,
                billing_cycle = :cycle,
                seats_purchased = :seats,
                current_period_start = :period_start,
                current_period_end = :period_end,
                next_plan_code = NULL,
                next_billing_cycle = NULL,
                next_seats = NULL
            WHERE id = :id
              AND next_plan_code IS NOT NULL
              AND current_period_end <= :now
              AND status = :status
            """
        ),
        {
            "plan_code": sub.next_plan_code,
            "cycle": new_cycle,
            "seats": new_seats,
            "period_start": new_start,
            "period_end": new_end,
            "id": sub.id,
            "now": now,
            "status": sub.status,
        },
    )
    if (result.rowcount or 0) == 0:
        return None

    await audit.log(
        "subscription.scheduled_change_applied",
        org_id=sub.org_id,
        entity_type="subscription",
        entity_id=sub.id,
        before={
            "plan_code": sub.plan_code,
            "billing_cycle": sub.billing_cycle,
            "seats_purchased": sub.seats_purchased,
        },
        after={
            "plan_code": sub.next_plan_code,
            "billing_cycle": new_cycle,
            "seats_purchased": new_seats,
            "current_period_start": new_start.isoformat(),
            "current_period_end": new_end.isoformat(),
        },
        user_id=None,  # system actor
    )
    return {"from_plan": sub.plan_code, "to_plan": sub.next_plan_code}


# ---------------------------------------------------------------------------
# 3-day reminder
# ---------------------------------------------------------------------------

async def fire_due_reminders(session: AsyncSession) -> int:
    """Send the `trial_ending_soon` email to every trialing sub whose
    `trial_ends_at` is within the next 3 days and that has not been
    notified yet.

    Dedup uses `subscriptions.reminders_sent['trial_ending_soon']`:
    we set it before the email queues (best-effort log line, can't
    really fail) so a beat retry after a crash won't double-notify.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = now + TRIAL_REMINDER_LEAD

    rows = (
        await session.execute(
            select(Subscription).where(
                Subscription.status == "trialing",
                Subscription.trial_ends_at > now,
                Subscription.trial_ends_at <= cutoff,
            )
        )
    ).scalars().all()

    fired = 0
    for sub in rows:
        if (sub.reminders_sent or {}).get("trial_ending_soon"):
            continue

        # Mark first, send after — a worker crash between the two
        # produces silence rather than a duplicate.
        update = await session.execute(
            text(
                "UPDATE subscriptions "
                "SET reminders_sent = reminders_sent || '{\"trial_ending_soon\": true}'::jsonb "
                "WHERE id = :id "
                "AND status = 'trialing' "
                "AND COALESCE(reminders_sent->>'trial_ending_soon', 'false') <> 'true'"
            ),
            {"id": sub.id},
        )
        if (update.rowcount or 0) == 0:
            continue

        days_remaining = max(
            0,
            (sub.trial_ends_at - now).days  # type: ignore[union-attr]
            + (1 if (sub.trial_ends_at - now).seconds > 0 else 0),  # type: ignore[union-attr]
        )
        await send_billing_email(
            org_id=sub.org_id,
            template_key="trial_ending_soon",
            context={
                "subscription_id": str(sub.id),
                "days_remaining": days_remaining,
                "trial_ends_at": sub.trial_ends_at.isoformat(),  # type: ignore[union-attr]
            },
        )
        fired += 1
    return fired
