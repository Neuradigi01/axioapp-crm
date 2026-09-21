# Step 5: Orphan-endpoint sweeper + admin overview smoke

**Status:** Pending

## Goal

Nightly Celery beat that soft-deletes orphan endpoints (no details row for 24h + no recent inbound). Admin overview endpoint smoke. Closes Track 1.

## Files touched

- `api/src/app/core/channel_endpoints/tasks.py` — Celery task `sweep_orphan_endpoints`
- `api/src/app/celery/worker.py` — autodiscover new task list entry
- `api/src/app/shared/celery_config.py` — beat entry `sweep-orphan-endpoints-nightly` (03:15 UTC)
- `api/tests/test_orphan_endpoint_sweeper.py`
- `tasks/email-endpoint-abstraction/SMOKE.md` — manual smoke checklist

## What this step does

- Task `sweep_orphan_endpoints()`:
  - Find endpoints where `EmailEndpointDetails IS NULL` AND `endpoint.created_at < now() - 24h`. Soft-delete (set `is_active=false`, `deactivated_at=now()`, `deactivation_reason='orphan_sweeper'`).
  - Also find endpoints for OAuth accounts that have been revoked (checked via `EmailAccount.status != 'active'` for > 7d). Soft-delete same way.
  - Log summary: N endpoints soft-deleted, list of endpoint IDs + reasons.
- Beat entry runs 03:15 UTC daily.
- Register in `celery.autodiscover_tasks([...])` list per memory `feedback_celery_task_autodiscover_list.md`.
- SMOKE.md manual checklist:
  1. Hit `GET /api/v1/channel-endpoints` → returns endpoint list including all backfilled rows
  2. Hit `POST /api/v1/channel-endpoints/{id}/deactivate` as Owner → 204, endpoint disappears from next list
  3. Try same as non-Owner → 403
  4. Try to access another org's endpoint by ID → 404

## Tests

- `test_sweeper_soft_deletes_orphan_endpoint_older_than_24h`
- `test_sweeper_skips_endpoints_with_details_row`
- `test_sweeper_soft_deletes_endpoints_for_revoked_oauth_accounts`
- `test_sweeper_writes_audit_event_per_soft_delete`
- `test_sweeper_beat_entry_registered_at_0315_utc`
- `test_sweeper_task_in_autodiscover_list`

## Verification checklist

- [ ] Beat entry visible in `celery beat` output
- [ ] Task appears in `celery inspect registered`
- [ ] SMOKE.md 4 checks pass in browser (Ajay's Workspace)
- [ ] Ruff clean
- [ ] Prettier clean (n/a — no frontend)

## Self-check

- Rule 10: pass.
- Layered: task calls service which calls DAL.
- Reuse: pass — uses Step 2's `soft_delete_orphans_older_than()`.

## Stop-and-report

Report smoke results, beat entry visible, test pass count. **Track 1 done. Awaiting your "proceed" for Track 2 step 1.**
