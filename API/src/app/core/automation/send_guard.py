"""Send-time compliance enforcement for automation runs.

Three checks gate any marketing-category run before the channel
adapter ships the message:

  1. **DPDP suppression** — the recipient contact must have opted
     in to the channel. For WhatsApp the check reads
     ``Contact.whatsapp_opt_in_status``; for email the check reads
     ``Contact.email_opt_out`` (DPDP / CAN-SPAM equivalence). Other
     channels fall through (the dedicated channel-consent columns
     don't exist yet — defer per Step 13 out-of-scope).
  2. **Frequency cap** — when
     ``Organization.marketing_frequency_cap_enabled`` is true, no
     contact receives more than
     ``Organization.marketing_frequency_cap_per_week`` marketing
     sends in any rolling 7-day window. Cap = 0 means "no marketing
     sends".
  3. **Quiet hours** — marketing sends inside the
     ``[quiet_hours_start, quiet_hours_end)`` window in
     ``Organization.quiet_hours_timezone`` are deferred to the
     window's end, not dropped.

Transactional + service templates BYPASS all three checks — those
carry legitimate-interest basis under DPDP and need to land
regardless of consent or time-of-day (think: order receipts, OTPs,
shipment notifications).

The composite ``evaluate(run)`` returns a :class:`SendDecision`
with one of three terminal states:

  * ``allow`` — proceed with the send.
  * ``defer_until`` — re-queue the Celery task with
    ``apply_async(eta=defer_until)``. Run status stays ``queued``.
  * ``skip_reason`` — write ``status=skipped`` + ``error=reason``.
    No send. Audit event ``automations.send_blocked_<reason>``
    emitted.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional

try:
    # Python 3.9+ ships zoneinfo; the project is on 3.13.
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — defensive only
    ZoneInfo = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


# Rolling-window length for the frequency cap. Matches the spec
# constant + the column name (``marketing_frequency_cap_per_week``).
_FREQUENCY_CAP_WINDOW = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class SendDecision:
    """Composite send-guard verdict for a single automation run."""

    allow: bool
    defer_until: Optional[datetime] = None
    skip_reason: Optional[str] = None


# A sentinel "no-op" decision the dispatcher uses when the run is
# not subject to send-guard rules (transactional + service
# categories bypass entirely).
_ALLOW = SendDecision(allow=True)


# --- DPDP suppression ----------------------------------------------------


def check_dpdp_suppression(
    *,
    channel: str,
    contact,
) -> SendDecision:
    """Return ``allow=False`` when the contact has explicitly opted
    out of the channel. Missing contact (e.g. recipient was a free
    string at trigger time) falls through to allow — the suppression
    check only fires when we have a tenant-managed Contact row.

    * WhatsApp: ``whatsapp_opt_in_status='opted_out'`` blocks.
      ``never_contacted`` + ``implicit`` ALLOW — DPDP service-message
      grace under inferred consent.
    * Email: ``email_opt_out=true`` blocks.
    * SMS / push / FB / IG: no per-channel suppression column today;
      allow.
    """
    if contact is None:
        return _ALLOW
    channel_lower = (channel or "").lower()
    if channel_lower == "whatsapp":
        status = getattr(contact, "whatsapp_opt_in_status", None)
        if str(status) == "opted_out":
            return SendDecision(allow=False, skip_reason="dpdp_suppressed")
        return _ALLOW
    if channel_lower == "email":
        if bool(getattr(contact, "email_opt_out", False)):
            return SendDecision(allow=False, skip_reason="dpdp_suppressed")
        return _ALLOW
    return _ALLOW


# --- Frequency cap -------------------------------------------------------


async def check_frequency_cap(
    session,
    *,
    org,
    contact_id: Optional[uuid.UUID],
    now_utc: datetime,
) -> SendDecision:
    """Return ``allow=False`` when the contact has already received
    ``cap_per_week`` marketing sends in the rolling 7-day window
    before ``now_utc``.

    Falls through to allow when:

      * ``cap_enabled=False`` (operator disabled the cap entirely)
      * ``contact_id is None`` (recipient wasn't a tenant Contact —
        the cap is per-contact only)
    """
    if not getattr(org, "marketing_frequency_cap_enabled", True):
        return _ALLOW
    if contact_id is None:
        return _ALLOW

    cap = int(getattr(org, "marketing_frequency_cap_per_week", 3))

    # Cap = 0 means "no marketing sends ever"; short-circuit so we
    # don't even fire the COUNT query.
    if cap <= 0:
        return SendDecision(
            allow=False, skip_reason="frequency_cap_exceeded"
        )

    from src.app.core.automation import data_access as _da

    since = now_utc - _FREQUENCY_CAP_WINDOW
    sent_count = await _da.count_marketing_runs_for_contact(
        session,
        org_id=org.id,
        contact_id=contact_id,
        since=since,
    )
    if sent_count >= cap:
        return SendDecision(
            allow=False, skip_reason="frequency_cap_exceeded"
        )
    return _ALLOW


# --- Quiet hours ---------------------------------------------------------


def _within_quiet_hours(*, now_local: time, start: time, end: time) -> bool:
    """``now_local`` falls inside ``[start, end)`` window.

    Wrap-midnight aware: when ``start > end`` (e.g. 21:00 → 09:00)
    the window crosses midnight + the inside-test inverts to
    ``now >= start OR now < end``.

    ``start == end`` means "no quiet hours" — always returns False.
    """
    if start == end:
        return False
    if start < end:
        # Same-day window (e.g. 13:00 → 17:00).
        return start <= now_local < end
    # Wrap-midnight window (e.g. 21:00 → 09:00).
    return now_local >= start or now_local < end


def _next_quiet_hours_end(
    *,
    now_utc: datetime,
    tz_name: str,
    quiet_start: time,
    quiet_end: time,
) -> datetime:
    """Compute the next UTC instant at which ``quiet_end`` is
    reached in the org's timezone, given that ``now_utc`` already
    falls inside the quiet window.

    The result is timezone-aware UTC so Celery's
    ``apply_async(eta=...)`` consumes it directly.
    """
    if ZoneInfo is None:  # pragma: no cover — Python ≥ 3.9 always has it
        return now_utc + timedelta(hours=1)

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Defensive: a bad tz string (operator typo) falls back to
        # UTC so the run still defers somewhere sensible rather than
        # crashing the worker.
        tz = ZoneInfo("UTC")

    now_local = now_utc.astimezone(tz)
    today_end = now_local.replace(
        hour=quiet_end.hour,
        minute=quiet_end.minute,
        second=0,
        microsecond=0,
    )
    # When quiet hours wrap midnight (21:00 → 09:00) and we're past
    # midnight (00:00 → 09:00), ``today_end`` is already today; when
    # we're pre-midnight (21:00 → 23:59), ``today_end`` is tomorrow.
    if quiet_start > quiet_end:
        # Wrap-midnight: defer to today_end if it's still ahead of
        # us, otherwise tomorrow's end.
        if today_end <= now_local:
            today_end = today_end + timedelta(days=1)
    else:
        # Non-wrap: defer to today_end while still inside the
        # window; never schedules into the past.
        if today_end <= now_local:
            today_end = today_end + timedelta(days=1)
    return today_end.astimezone(timezone.utc)


def check_quiet_hours(
    *,
    org,
    now_utc: datetime,
) -> SendDecision:
    """Return a ``defer_until`` decision when ``now_utc`` falls
    inside the org's quiet-hours window; otherwise allow.

    Bad timezone strings degrade to "no quiet hours" rather than
    crashing the dispatcher — operators get an immediate send + the
    audit log surfaces the tz-resolution warning.
    """
    if ZoneInfo is None:  # pragma: no cover
        return _ALLOW

    tz_name = getattr(org, "quiet_hours_timezone", "Asia/Kolkata") or "UTC"
    quiet_start = getattr(org, "quiet_hours_start", None)
    quiet_end = getattr(org, "quiet_hours_end", None)
    if quiet_start is None or quiet_end is None:
        return _ALLOW

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning(
            "send_guard.check_quiet_hours bad_timezone tz=%s org=%s",
            tz_name,
            getattr(org, "id", None),
        )
        return _ALLOW

    now_local = now_utc.astimezone(tz).time()
    if not _within_quiet_hours(
        now_local=now_local, start=quiet_start, end=quiet_end
    ):
        return _ALLOW

    defer_until = _next_quiet_hours_end(
        now_utc=now_utc,
        tz_name=tz_name,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
    )
    return SendDecision(allow=False, defer_until=defer_until)


# --- Composite -----------------------------------------------------------


async def evaluate(
    session,
    *,
    org,
    template,
    contact,
    contact_id: Optional[uuid.UUID],
    channel: str,
    now_utc: Optional[datetime] = None,
) -> SendDecision:
    """Composite verdict: returns the first non-allow decision found,
    or ``SendDecision(allow=True)`` if all three checks pass.

    Order:
      1. DPDP suppression  → ``skip_reason='dpdp_suppressed'``
      2. Frequency cap     → ``skip_reason='frequency_cap_exceeded'``
      3. Quiet hours       → ``defer_until=<utc>``

    Transactional + service templates short-circuit to allow without
    running any check — legitimate-interest basis under DPDP +
    business courtesy."""
    from src.app.core.templates.models import TemplateCategory

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    category = getattr(template, "category", None)
    if category != TemplateCategory.marketing:
        return _ALLOW

    dpdp = check_dpdp_suppression(channel=channel, contact=contact)
    if not dpdp.allow:
        return dpdp

    freq = await check_frequency_cap(
        session, org=org, contact_id=contact_id, now_utc=now_utc
    )
    if not freq.allow:
        return freq

    quiet = check_quiet_hours(org=org, now_utc=now_utc)
    if not quiet.allow:
        return quiet

    return _ALLOW


__all__ = [
    "SendDecision",
    "check_dpdp_suppression",
    "check_frequency_cap",
    "check_quiet_hours",
    "evaluate",
]
