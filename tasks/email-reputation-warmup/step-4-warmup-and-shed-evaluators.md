# Step 4: Warmup evaluator (4h beat) + shed evaluator + owner notifications

**Status:** Pending

## Goal

Automated warmup-stage advance and reputation-threshold shed. Owner notified at every transition. All logic in service layer; beat schedules cadence.

## Files touched

- `api/src/app/core/email/reputation/warmup.py` — evaluator functions
- `api/src/app/core/email/reputation/shed.py` — threshold evaluator
- `api/src/app/core/email/reputation/tasks.py` — Celery tasks
- `api/src/app/celery/worker.py` — autodiscover
- `api/src/app/shared/celery_config.py` — 3 beat entries
- `api/tests/test_warmup_evaluator.py`
- `api/tests/test_shed_evaluator.py`

## What this step does

- `warmup.py`:
  - `evaluate_warmup_for_row(db, row)`:
    - Read counters: `sent_last_24h`, `complaints_last_24h`, `bounces_last_24h`.
    - Current stage cap from `EMAIL_WARMUP_STAGE_CAPS` env list.
    - Advance condition: `sent_last_24h >= cap * EARN_FRACTION (0.5)` AND thresholds under.
    - If advance: `warmup_stage += 1`, `warmup_stage_earned_at = now()`, `warmup_stage_current_sent = 0`. Notify owner `warmup_advanced` in-app.
    - Row-lock via `SELECT ... FOR UPDATE`.
- `shed.py`:
  - `evaluate_shed_for_row(db, row)`:
    - Read counters.
    - `delivered = delivered_last_24h`.
    - `total_events = delivered + bounces + complaints`.
    - If `total_events < EMAIL_REPUTATION_MIN_EVENTS (100)`: skip.
    - `complaint_rate = complaints / delivered`. Threshold breached → shed.
    - `bounce_rate = bounces / delivered`. Threshold breached → shed.
    - Shed action: `reputation_state = 'blocked'`, `blocked_until = now() + EMAIL_BREACH_COOLDOWN_HOURS (4)`, `warmup_stage = 0`. Notify owner `reputation_blocked`.
    - Recovery: if `now() >= blocked_until`, flip `reputation_state = 'ok'`, notify `reputation_recovered`.
    - Warning zone (80% of threshold): `reputation_state = 'warned'`, notify `reputation_warning`.
- Celery tasks + beat:
  - `evaluate_warmup_and_shed_4h` at every 4 hours.
  - `check_blocked_until_expiry_hourly` at every hour.

## Tests

- `test_warmup_advance_after_50pct_sent_under_thresholds`
- `test_warmup_does_not_advance_below_earn_fraction`
- `test_warmup_does_not_advance_when_thresholds_breached`
- `test_warmup_platform_from_and_own_domain_advance_independently`
- `test_warmup_notify_owner_on_advance`
- `test_shed_below_event_floor_skips`
- `test_shed_at_event_floor_100_evaluates`
- `test_shed_complaint_rate_over_threshold_blocks`
- `test_shed_bounce_rate_over_threshold_blocks`
- `test_shed_blocks_for_cooldown_hours`
- `test_shed_resets_warmup_stage_to_0`
- `test_shed_recovery_after_blocked_until_expires_notifies_owner`
- `test_shed_warning_zone_at_80pct_threshold_notifies_owner`
- `test_evaluator_row_locked_for_update`

## Verification checklist

- [ ] All 14 tests pass
- [ ] Beat entries registered
- [ ] Tasks in autodiscover list
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- Layered: pass.
- DB efficiency: pass — `FOR UPDATE` on lock; single counter-read pipeline per row.

## Stop-and-report

Report file count, test pass, beat entries visible. **Awaiting your "proceed" for Step 5.**
