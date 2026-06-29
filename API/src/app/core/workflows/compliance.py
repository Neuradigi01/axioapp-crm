"""Compliance-gate pre-flight for workflow Send actions — Step 12.

The Send-action handlers (Step 7) call :func:`check_send` BEFORE
shipping the message. The decision determines the action result:

  * :class:`Allow`               → handler proceeds with the send.
  * :class:`Skip(reason)`        → handler returns
                                  ``ActionResult(skip_reason=reason)``.
  * :class:`Defer(until, ...)`   → handler returns
                                  ``ActionResult(skip_reason='deferred_*')``
                                  AND sets ``run.next_step_at = until``
                                  + ``run.status='pending'`` so the
                                  Step-4 beat sweep resumes the SAME
                                  node later (no new step_run row;
                                  the existing one's skip_reason gets
                                  overwritten on the retry).

Marketing-category gates (in order — short-circuit on first non-Allow):

  1. **Block list** (placeholder — no ``tbl_block_list`` in v1
     schema; the check is a no-op until that table ships).
  2. **Opt-out** — channel-aware: email checks
     ``contact.email_opt_out``; WhatsApp checks
     ``contact.whatsapp_opt_in_status='opted_out'``.
  3. **Quiet hours** — when ``now()`` falls inside
     ``[quiet_hours_start, quiet_hours_end)`` in the org tz, return
     ``Defer(until=quiet_hours_end_today_or_tomorrow)``. Wraps
     midnight correctly (start>end means "21:00 today through 09:00
     tomorrow").
  4. **Frequency cap** — per-week + per-day counts via the DAL's
     :func:`core.workflows.data_access.count_recent_marketing_sends`.

Transactional + service-category sends:
  * Block list still applies (DND is absolute; not bypassed even by
    transactional sends — a hard-bounced address shouldn't receive
    an invoice either).
  * Other gates honour the per-org ``transactional_bypass_*`` flags.

Two extra utilities:

  * :func:`ensure_unsubscribe_link` — for marketing email sends,
    appends a standard footer when the org's
    ``unsubscribe_link_required_in_marketing_email=True`` AND the
    rendered body lacks an ``unsubscribe`` token.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Allow:
    """Send may proceed. Carries no payload."""


@dataclass(slots=True)
class Skip:
    """Send blocked permanently. ``reason`` lands as
    ``ActionResult.skip_reason`` so the run-history view shows
    why."""

    reason: str


@dataclass(slots=True)
class Defer:
    """Send postponed until ``until``. The Send handler sets the
    run's ``next_step_at`` so the Step-4 beat sweep resumes the
    same step. ``reason`` lands as ``ActionResult.skip_reason``
    (e.g. ``deferred_quiet_hours``) on the current step_run; the
    resumed step overwrites with the success status."""

    until: datetime
    reason: str


ComplianceDecision = Allow | Skip | Defer


# ---------------------------------------------------------------------------
# Compliance settings cache (one read per run; the value rarely
# changes mid-run, so we don't bother with TTL — settings are read
# fresh on each Send action's pre-flight).
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ComplianceSettings:
    """In-memory snapshot of the OrgSettings columns this module
    reads. Built once per ``check_send`` call."""

    quiet_hours_enabled: bool
    quiet_hours_start: time
    quiet_hours_end: time
    quiet_hours_timezone: str
    frequency_cap_marketing_per_week: int
    frequency_cap_marketing_per_day: int
    transactional_bypass_quiet_hours: bool
    transactional_bypass_frequency_cap: bool
    unsubscribe_link_required_in_marketing_email: bool


async def _load_settings(session, *, org_id: uuid.UUID) -> _ComplianceSettings:
    """Load the compliance section of OrgSettings. Falls back to
    documented defaults when the row is missing (shouldn't happen
    post-org-create but defends against bare test orgs)."""
    from sqlalchemy import select

    from src.app.core.settings.models import OrgSettings

    row = (
        await session.execute(
            select(OrgSettings).where(OrgSettings.org_id == org_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return _ComplianceSettings(
            quiet_hours_enabled=True,
            quiet_hours_start=time(21, 0),
            quiet_hours_end=time(9, 0),
            quiet_hours_timezone="Asia/Kolkata",
            frequency_cap_marketing_per_week=5,
            frequency_cap_marketing_per_day=2,
            transactional_bypass_quiet_hours=True,
            transactional_bypass_frequency_cap=True,
            unsubscribe_link_required_in_marketing_email=True,
        )
    return _ComplianceSettings(
        quiet_hours_enabled=row.quiet_hours_enabled,
        quiet_hours_start=row.quiet_hours_start,
        quiet_hours_end=row.quiet_hours_end,
        quiet_hours_timezone=row.quiet_hours_timezone,
        frequency_cap_marketing_per_week=row.frequency_cap_marketing_per_week,
        frequency_cap_marketing_per_day=row.frequency_cap_marketing_per_day,
        transactional_bypass_quiet_hours=row.transactional_bypass_quiet_hours,
        transactional_bypass_frequency_cap=row.transactional_bypass_frequency_cap,
        unsubscribe_link_required_in_marketing_email=(
            row.unsubscribe_link_required_in_marketing_email
        ),
    )


# ---------------------------------------------------------------------------
# Block list + opt-out checks
# ---------------------------------------------------------------------------


async def _check_block_list(
    session, *, org_id: uuid.UUID, contact_id: uuid.UUID | None
) -> bool:
    """Returns True iff the contact is on a block list. v1 has no
    dedicated ``tbl_block_list`` table — the check is a no-op +
    returns False so all sends proceed. A future track that ships
    the block list will replace this body."""
    return False


async def _check_opt_out(
    session,
    *,
    contact_id: uuid.UUID | None,
    channel: str,
) -> bool:
    """Returns True iff the contact has opted out of the SPECIFIC
    channel. Email checks ``contact.email_opt_out``; WhatsApp checks
    ``contact.whatsapp_opt_in_status='opted_out'``. Other channels
    have no opt-out column yet — return False."""
    if contact_id is None:
        return False
    from sqlalchemy import select

    from src.app.core.contacts.models import Contact

    contact = (
        await session.execute(
            select(Contact).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        return False

    channel_lower = (channel or "").lower()
    if channel_lower == "email":
        return bool(contact.email_opt_out)
    if channel_lower == "whatsapp":
        return contact.whatsapp_opt_in_status == "opted_out"
    return False


# ---------------------------------------------------------------------------
# Quiet hours (with midnight-wrap handling)
# ---------------------------------------------------------------------------


def _resolve_quiet_hours_defer(
    settings: _ComplianceSettings, *, now: datetime
) -> datetime | None:
    """Return the UTC ``defer_until`` datetime when ``now`` falls
    inside the org's quiet-hours window, otherwise None.

    Handles the wrap-midnight case (start > end means
    ``[21:00 today, 09:00 tomorrow]``)."""
    if not settings.quiet_hours_enabled:
        return None

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(settings.quiet_hours_timezone)
    except Exception:
        # Bad tz string in settings → fall back to UTC + log once
        # at WARN so the operator can fix it.
        logger.warning(
            "compliance.quiet_hours bad_timezone tz=%s — defaulting to UTC",
            settings.quiet_hours_timezone,
        )
        tz = timezone.utc

    local_now = now.astimezone(tz)
    start = settings.quiet_hours_start
    end = settings.quiet_hours_end
    now_t = local_now.time()

    in_window: bool
    if start == end:
        # Sentinel: empty window means "no quiet hours".
        return None
    if start < end:
        # Daytime-only window, e.g. 13:00 → 14:00 (rare but valid).
        in_window = start <= now_t < end
    else:
        # Wrap-midnight window — e.g. 21:00 → 09:00.
        in_window = now_t >= start or now_t < end

    if not in_window:
        return None

    # Compute "next end_time in local tz" — if we're past midnight
    # (now_t < end), that's today; otherwise tomorrow.
    if start < end:
        # Within a daytime-only window, end is today.
        defer_local = datetime.combine(local_now.date(), end, tzinfo=tz)
    else:
        if now_t < end:
            # Past midnight, end is today.
            defer_local = datetime.combine(local_now.date(), end, tzinfo=tz)
        else:
            # Before midnight, end is tomorrow.
            defer_local = datetime.combine(
                local_now.date() + timedelta(days=1), end, tzinfo=tz
            )
    return defer_local.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Frequency cap
# ---------------------------------------------------------------------------


async def _check_frequency_caps(
    session,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    settings: _ComplianceSettings,
    now: datetime,
) -> str | None:
    """Returns the skip-reason string when EITHER the per-week OR
    per-day cap is exceeded; None when both pass.

    Per-day cap fires INDEPENDENTLY of the per-week cap — an org
    that wants "5/week max but at most 2 per day" gets both
    behaviours by setting both to their non-zero values. Setting
    either to 0 disables that side."""
    from src.app.core.workflows import data_access as _wf_da

    weekly_cap = settings.frequency_cap_marketing_per_week
    daily_cap = settings.frequency_cap_marketing_per_day

    if daily_cap > 0:
        since_day = now - timedelta(days=1)
        day_count = await _wf_da.count_recent_marketing_sends(
            session, org_id=org_id, contact_id=contact_id, since=since_day
        )
        if day_count >= daily_cap:
            return "frequency_cap_day"

    if weekly_cap > 0:
        since_week = now - timedelta(days=7)
        week_count = await _wf_da.count_recent_marketing_sends(
            session, org_id=org_id, contact_id=contact_id, since=since_week
        )
        if week_count >= weekly_cap:
            return "frequency_cap"

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def check_send(
    session,
    *,
    run,
    node: dict[str, Any],
    recipient: str | None,
    channel: str,
    category: str,
    now: datetime | None = None,
) -> ComplianceDecision:
    """Composite compliance pre-flight for a Send action.

    Returns:
      * ``Allow`` — proceed with the send.
      * ``Skip(reason)`` — refuse + record the reason on step_run.
      * ``Defer(until, reason)`` — postpone; caller sets
        ``run.next_step_at = until``.

    The Step-7 send.* handlers translate the decision into the
    ActionResult shape the engine expects.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    org_id = getattr(run, "org_id", None)
    contact_id = getattr(run, "contact_id", None)
    if org_id is None:
        # Defensive — engine always sets org_id on the run row.
        return Allow()

    settings = await _load_settings(session, org_id=org_id)

    # 1) Block list applies to ALL categories. v1 is a no-op.
    if await _check_block_list(
        session, org_id=org_id, contact_id=contact_id
    ):
        return Skip(reason="blocked")

    category_lower = (category or "").lower()

    if category_lower == "marketing":
        # 2) Channel-aware opt-out.
        if await _check_opt_out(
            session, contact_id=contact_id, channel=channel
        ):
            return Skip(reason="opt_out")

        # 3) Quiet hours.
        defer_until = _resolve_quiet_hours_defer(settings, now=now)
        if defer_until is not None:
            return Defer(until=defer_until, reason="deferred_quiet_hours")

        # 4) Frequency cap. Skipped when no contact_id (contactless
        # marketing sends are rare but possible).
        if contact_id is not None:
            cap_reason = await _check_frequency_caps(
                session,
                org_id=org_id,
                contact_id=contact_id,
                settings=settings,
                now=now,
            )
            if cap_reason is not None:
                return Skip(reason=cap_reason)

        return Allow()

    # Transactional + service categories.
    if not settings.transactional_bypass_quiet_hours:
        defer_until = _resolve_quiet_hours_defer(settings, now=now)
        if defer_until is not None:
            return Defer(until=defer_until, reason="deferred_quiet_hours")

    if (
        not settings.transactional_bypass_frequency_cap
        and contact_id is not None
    ):
        cap_reason = await _check_frequency_caps(
            session,
            org_id=org_id,
            contact_id=contact_id,
            settings=settings,
            now=now,
        )
        if cap_reason is not None:
            return Skip(reason=cap_reason)

    return Allow()


# ---------------------------------------------------------------------------
# Unsubscribe-link auto-injection (email marketing only)
# ---------------------------------------------------------------------------


_UNSUBSCRIBE_TOKEN_HINTS = ("unsubscribe", "{{ unsubscribe", "[unsubscribe]")


async def ensure_unsubscribe_link(
    session,
    *,
    org_id: uuid.UUID,
    category: str,
    channel: str,
    body: str,
) -> tuple[str, bool]:
    """When the org requires an unsubscribe link in marketing email
    AND the rendered body doesn't already carry one, append a
    standard footer. Returns the (possibly-modified) body + a
    boolean indicating whether the footer was injected (so the
    Send handler can attach a diagnostic note to the step_run).
    """
    if (channel or "").lower() != "email":
        return body, False
    if (category or "").lower() != "marketing":
        return body, False

    settings = await _load_settings(session, org_id=org_id)
    if not settings.unsubscribe_link_required_in_marketing_email:
        return body, False

    lower = (body or "").lower()
    if any(hint.lower() in lower for hint in _UNSUBSCRIBE_TOKEN_HINTS):
        return body, False

    footer = (
        "\n\n---\n"
        "To unsubscribe from these emails, reply with STOP or visit "
        "{{ unsubscribe_url }}."
    )
    return (body or "") + footer, True


__all__ = [
    "Allow",
    "ComplianceDecision",
    "Defer",
    "Skip",
    "check_send",
    "ensure_unsubscribe_link",
]
