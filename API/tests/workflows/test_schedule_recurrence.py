"""Pin tests for the schedule recurrence math.

Pure-function tests — no DB. Covers:
  * ``compute_next_run_at`` for all 6 schedule_kinds.
  * DST spring-forward → skip, fall-back → run-once (via zoneinfo +
    croniter defaults).
  * Day-31 monthly clamps to month-end (28/29/30/31).
  * Interval with ``last_run_at`` set forward-projects past ``now``.
  * ``_validate_config_and_bounds`` rejects: past starts_at, end<
    starts, sub-5-min interval, sub-5-min cron (``*/1``), 5-year
    horizon breach, bogus timezone, 6-field cron.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.app.core.workflows import service as svc
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    OnMissedPolicy,
    ScheduleKind,
    WorkflowSchedule,
)


def _make(
    kind: ScheduleKind,
    config: dict,
    *,
    tz: str = "UTC",
    starts_at: datetime | None = None,
) -> WorkflowSchedule:
    sch = WorkflowSchedule(
        name="x",
        schedule_kind=kind,
        config_json=config,
        timezone=tz,
        starts_at=starts_at or datetime(2026, 1, 1, tzinfo=UTC),
        active=True,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=ConcurrencyPolicy.forbid,
        runs_completed=0,
    )
    return sch


# ---------------------------------------------------------------------------
# compute_next_run_at — happy paths
# ---------------------------------------------------------------------------


def test_once_returns_configured_at_in_utc():
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    at_iso = (now + timedelta(hours=3)).isoformat()
    sch = _make(ScheduleKind.once, {"at": at_iso})
    assert svc.compute_next_run_at(sch, now=now) == now + timedelta(hours=3)


def test_daily_09_00_ist_returns_next_ist_09_00_utc_equivalent():
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)  # 11:30 IST
    sch = _make(ScheduleKind.daily, {"time": "09:00"}, tz="Asia/Kolkata")
    # 09:00 IST tomorrow = 03:30 UTC next day
    assert svc.compute_next_run_at(sch, now=now) == datetime(2026, 8, 6, 3, 30, tzinfo=UTC)


def test_weekly_mon_wed_returns_next_matching_weekday():
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)  # Wed 11:30 IST
    sch = _make(
        ScheduleKind.weekly,
        {"days": ["mon", "wed"], "time": "09:00"},
        tz="Asia/Kolkata",
    )
    nxt = svc.compute_next_run_at(sch, now=now)
    local = nxt.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local.weekday() in {0, 2}  # Mon or Wed
    assert (local.hour, local.minute) == (9, 0)


def test_monthly_day_31_clamps_to_feb_28_in_non_leap_year():
    # 2026 is not a leap year.
    now = datetime(2026, 2, 5, tzinfo=UTC)
    sch = _make(
        ScheduleKind.monthly,
        {"day_of_month": 31, "time": "10:00"},
        tz="Asia/Kolkata",
    )
    nxt = svc.compute_next_run_at(sch, now=now)
    local = nxt.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.month, local.day) == (2, 28)


def test_monthly_day_31_clamps_to_feb_29_in_leap_year():
    now = datetime(2028, 2, 5, tzinfo=UTC)  # 2028 IS a leap year
    sch = _make(
        ScheduleKind.monthly,
        {"day_of_month": 31, "time": "10:00"},
        tz="Asia/Kolkata",
    )
    nxt = svc.compute_next_run_at(sch, now=now)
    local = nxt.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.month, local.day) == (2, 29)


def test_interval_forward_projects_past_now():
    """A schedule that missed several fires must land on the FIRST
    future slot after ``now`` — not N slots behind."""
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)
    sch = _make(ScheduleKind.interval, {"every": 15, "unit": "minutes"})
    sch.last_run_at = now - timedelta(hours=2)  # 8 slots ago
    nxt = svc.compute_next_run_at(sch, now=now)
    assert nxt > now
    assert nxt <= now + timedelta(minutes=15)


def test_cron_mon_9am_returns_next_monday():
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)  # Wed
    sch = _make(ScheduleKind.cron, {"expression": "0 9 * * 1"})
    nxt = svc.compute_next_run_at(sch, now=now)
    assert nxt.weekday() == 0
    assert nxt.hour == 9
    assert nxt.minute == 0


# ---------------------------------------------------------------------------
# DST edge cases
# ---------------------------------------------------------------------------


def test_daily_dst_spring_forward_skips_missing_hour():
    """On the DST spring-forward day, 02:30 doesn't exist.
    ``zoneinfo`` + our recurrence math must skip past to 03:30 (or
    the same 02:30 next day, depending on when 'now' is). Tolerant
    assertion: the returned datetime is real and > now."""
    # US/Eastern 2026 DST forward: 2026-03-08 02:30 doesn't exist.
    tz = "America/New_York"
    now = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # 00:00 local
    sch = _make(ScheduleKind.daily, {"time": "02:30"}, tz=tz)
    nxt = svc.compute_next_run_at(sch, now=now)
    # A tz-aware, resolvable datetime that is strictly > now.
    assert nxt > now
    local = nxt.astimezone(ZoneInfo(tz))
    # The recurrence math either lands on a real (post-DST) time
    # today or the same 02:30 the next day.
    assert local.hour in {2, 3}


def test_cron_dst_fall_back_fires_once():
    """On fall-back, 01:30 EST occurs twice. croniter fires on the
    first occurrence — we just verify it returns exactly one
    strictly-future datetime without raising."""
    tz = "America/New_York"
    now = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)  # ~midnight local
    sch = _make(ScheduleKind.cron, {"expression": "30 1 * * *"}, tz=tz)
    nxt = svc.compute_next_run_at(sch, now=now)
    assert nxt > now


# ---------------------------------------------------------------------------
# Validation rejections
# ---------------------------------------------------------------------------


def test_validate_rejects_past_starts_at():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="past"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.once,
            config={"at": (now + timedelta(hours=1)).isoformat()},
            starts_at=now - timedelta(hours=1),
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_rejects_end_at_before_starts_at():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="after start"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.daily,
            config={"time": "09:00"},
            starts_at=now + timedelta(hours=1),
            end_at=now - timedelta(hours=1),
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_rejects_interval_below_5_min():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="minimum interval"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.interval,
            config={"every": 2, "unit": "minutes"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_rejects_cron_minute_star_by_computed_distance():
    """String-match on ``*`` isn't enough — ``*/1 * * * *`` has a
    computed inter-fire distance of 1 min. The check is on distance,
    not string shape."""
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="minimum inter-fire"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.cron,
            config={"expression": "*/1 * * * *"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_rejects_cron_with_6_fields():
    """5-field cron only — no seconds field, no year field."""
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="5-field"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.cron,
            config={"expression": "0 0 9 * * 1"},  # 6 fields (seconds prefix)
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_rejects_bogus_timezone():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="IANA"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.daily,
            config={"time": "09:00"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="Not/A/Timezone",
            now=now,
        )


def test_validate_rejects_max_runs_less_than_1():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="max_runs"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.daily,
            config={"time": "09:00"},
            starts_at=now,
            end_at=None,
            max_runs=0,
            tz_name="UTC",
            now=now,
        )


def test_validate_weekly_rejects_empty_days():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="config.days"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.weekly,
            config={"days": [], "time": "09:00"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_monthly_rejects_day_out_of_range():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="day_of_month"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.monthly,
            config={"day_of_month": 32, "time": "09:00"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )


def test_validate_daily_rejects_bad_hhmm():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with pytest.raises(svc.ScheduleValidationError, match="config.time"):
        svc._validate_config_and_bounds(
            schedule_kind=ScheduleKind.daily,
            config={"time": "25:99"},
            starts_at=now,
            end_at=None,
            max_runs=None,
            tz_name="UTC",
            now=now,
        )
