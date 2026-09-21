# Step 6: Nightly + hourly Celery beat + state-machine transitions + owner notifications

**Status:** COMPLETED

## Goal

Automated drift detection. Nightly re-verify of pending/verified; hourly re-verify of demoted. Automatic demote/release/re-verify transitions. Owner notified at every transition.

## Files touched

- `api/src/app/core/email_sender_setup/tasks.py` — new Celery tasks
- `api/src/app/celery/worker.py` — autodiscover new task list
- `api/src/app/shared/celery_config.py` — 2 beat entries
- `api/tests/test_sending_domains_cron.py`

## What this step does

- Task `sweep_email_domain_claims_nightly()`:
  - Loop all rows in `verification_status IN ('pending','verified')`.
  - Call `verify_domain(id=row.id, actor_user_id=None)` (system-actor).
  - Row-lock per-domain via `SELECT ... FOR UPDATE SKIP LOCKED`.
  - If `consecutive_failed_checks >= EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS (default 3)`: `mark_demoted()`, `demoted_at=now()`, notify owner (in-app + email `sending_domain_demoted`).
  - If `verification_status='verified'` and last was pending: send `sending_domain_verified` notification.
- Task `sweep_demoted_domains_hourly()`:
  - Loop all rows `verification_status='demoted'`.
  - Try `verify_domain()`. If all pass → `mark_verified_after_demotion()`, `demoted_at=NULL`, notify owner `sending_domain_recovered`.
  - If `demoted_at < now() - EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS (default 14)`: `release_domain()` (system-actor), notify owner `sending_domain_released_auto`.
- Beat entries:
  - `sweep-email-domains-nightly` at 04:00 UTC daily
  - `sweep-demoted-domains-hourly` every hour on the hour
- Register in `celery.autodiscover_tasks([...])`.

## Tests

- `test_nightly_sweep_re_verifies_pending_and_verified`
- `test_nightly_sweep_demotes_after_3_consecutive_failures`
- `test_nightly_sweep_sends_demote_notification_to_owner`
- `test_hourly_sweep_re_verifies_demoted_only`
- `test_hourly_sweep_recovers_when_all_pass_and_notifies`
- `test_hourly_sweep_releases_after_14_days_demoted`
- `test_sweep_row_lock_skip_locked_prevents_double_process`
- `test_sweep_mailgun_5xx_does_not_advance_failed_counter`
- `test_sweep_beat_entries_registered`
- `test_sweep_tasks_in_autodiscover_list`

## Verification checklist

- [ ] Both beat entries visible in `celery beat`
- [ ] Both tasks in `celery inspect registered`
- [ ] All 10 tests pass
- [ ] Config env vars set with defaults

## Self-check

- Rule 10: pass.
- DB efficiency: pass — `FOR UPDATE SKIP LOCKED` avoids lock contention.
- Layered: pass.
- Memory `feedback_celery_task_autodiscover_list.md`: pass.

## Stop-and-report

Report file count, test pass, beat schedule. **Awaiting your "proceed" for Step 7.**
