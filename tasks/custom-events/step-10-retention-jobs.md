# Step 10 — Retention: occurrence archive (90d, per-org iteration), partition rotation, test-runs cleanup (7d), key-rotation 12h alert

**Goal:** Celery Beat retention jobs. Occurrence archive job iterates per-org (never bulk-copies across orgs). Monthly partition rotation. `tbl_custom_event_test_runs` 7-day sweep. Key-rotation 12h "still using old key" alert email.
**Phase:** Custom Events track — step 10/17
**Depends on:** Steps 5, 6, 7c
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/custom_events/tasks.py`:
  - `archive_old_occurrences()` — daily. For each org: `SET rls.org_id = ?`; `INSERT INTO tbl_custom_event_occurrences_archive SELECT * FROM tbl_custom_event_occurrences WHERE org_id = ? AND fired_at < now() - INTERVAL '90 days'`; then `DELETE`. Never bulk-copies cross-org in one statement (integrity test asserts).
  - `rotate_occurrence_partitions()` — monthly (first day). Create next month's partition; detach + optionally drop 6-months-past partitions (retain in archive).
  - `cleanup_test_runs()` — daily. `DELETE FROM tbl_custom_event_test_runs WHERE fired_at < now() - INTERVAL '7 days'`.
- `core/public_ingest/api_keys/tasks.py`:
  - `check_old_key_usage_alerts()` — hourly (already added in Step 4). Verify still wired here.
- All jobs scheduled via existing Celery Beat config (`api/src/app/shared/celery_config.py` or equivalent).
- Post-archive integrity check per run: `SELECT COUNT(DISTINCT org_id) FROM archive WHERE archived_at = today` matches sum-per-org counts from source. Alert if mismatch.

**Out of scope:**
- Cleanup of `tbl_public_ingest_log` (existing embed retention rules apply).
- GDPR PII scrub of payload JSONB (follow-up `gdpr-payload-scrub` track).

## Files to touch
- `core/public_ingest/custom_events/tasks.py` (populated).
- `api/src/app/shared/celery_beat.py` (modified — schedule entries).
- Tests.

## Plan
1. Implement archive job with per-org iteration.
2. Partition rotation.
3. Test-runs cleanup.
4. Integrity checks + alerts on mismatch.
5. Tests.

## DB changes / migrations
None (partitions created dynamically by rotation job).

## Tests to add
- `test_archive_job_moves_rows_older_than_90d_per_org`.
- `test_archive_job_never_crosses_org_boundary_under_concurrent_writes`.
- `test_archive_job_uses_indexes_not_full_scan` (EXPLAIN check).
- `test_archive_job_integrity_check_alerts_on_mismatch`.
- `test_partition_rotation_creates_next_month`.
- `test_test_runs_cleanup_deletes_7_days_old`.
- `test_check_old_key_usage_alerts_emails_owner_when_still_in_use_at_12h` (from Step 4; re-verify wired).

## Verification checklist
- Backend: tests pass.
- Backend: Beat schedule includes new jobs.
- Backend: manual run archive job on fixture data; verify per-org isolation.

## Self-check
- [ ] Rules 1, 2 clean.
- [ ] Rule 8: 3 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
