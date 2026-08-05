# Step 6 — Data lifecycle — contact-merge cascade + orphan-run reaper + consecutive-empty deactivation + weekly orphan-schedule cleanup

**Goal:** Close the lifecycle loops the reviewers flagged: contacts merging/deleting, sweep crashing mid-commit, schedules silently resolving to nothing, orphan rows from historical bugs. All are safety nets that fire without operator action.

**Status:** Pending

**Depends on:** Step 5 (full stack operable so lifecycle can be exercised end-to-end)

---

## Scope

**In-scope:**
- **Contact merge cascade** in `core/contacts/service.py`: on merge (`merge_contacts_service`), repoint `tbl_workflow_schedules.contact_id` from loser → winner in the same transaction. Write `schedule.contact_repointed` audit rows per repointed schedule.
- **Contact delete cascade** in `core/contacts/service.py`: on hard delete, `UPDATE tbl_workflow_schedules SET active = false, deactivation_reason = 'contact_deleted', next_run_at = NULL WHERE contact_id = <deleted>`; write audit + owner-notification email per row.
- **Orphan-run reaper** in `core/workflows/tasks.py`: extend `sweep_waits` to include a third responsibility — `SELECT id FROM tbl_workflow_runs WHERE status = 'pending' AND started_at < now() - interval '1 hour' AND (SELECT count(*) FROM ... worker locks ...) = 0`; mark each `errored` with `error_reason = 'orphaned_pending'`. Rate-limited to 100 reaps per tick.
- **Consecutive-empty auto-deactivation**: in send-action handlers, when `audience_empty` is the outcome, increment `tbl_workflow_schedules.consecutive_empty_fires` (via service call). Sweep dispatch reads it; when ≥20, deactivate row + notify owner (`schedule.deactivated_consecutive_empty` audit).
- **Weekly orphan-schedule cleanup task** (`core/workflows/tasks.py` — beat entry, weekly): find schedules whose parent workflow is gone (impossible via FK, but historical bugs happen); repair-report per org.
- **Deactivation-notification email**: reusable template `email/schedule_deactivated.html`; sent to `workflow.created_by_user_id` (or `org.owner`) with schedule name, reason, and a link to the workflow detail page.

**Out-of-scope:**
- Retention policy for `tbl_workflow_runs` (Open item §10 in README).
- Consecutive-error auto-deactivation (Open item §7).
- Bulk pause across orgs (Open item §6).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/contacts/service.py` | edit — call schedule cascade methods from `merge_contacts_service` and `delete_contact_service` |
| `api/src/app/core/workflows/service.py` | edit — add `cascade_schedules_on_contact_merge`, `cascade_schedules_on_contact_delete`, `increment_consecutive_empty_fires`, `reap_orphaned_runs`, `sweep_orphan_schedules` |
| `api/src/app/core/workflows/data_access.py` | edit — add repoint/deactivate queries + orphan-run finder + orphan-schedule finder |
| `api/src/app/core/workflows/tasks.py` | edit — extend `sweep_waits` to also call reaper (100/tick); add new beat task `sweep_orphan_schedules_weekly` |
| `api/src/app/shared/celery_config.py` | edit — add weekly beat entry for the orphan sweeper |
| `api/src/app/core/workflows/actions/send.py` | edit — call `increment_consecutive_empty_fires` when audience empty (works via existing schedule-source-id on the run) |
| `api/src/app/core/notifications/templates/schedule_deactivated.html` | **NEW** — email template |
| `api/src/app/core/notifications/service.py` | edit — add `notify_schedule_deactivated(user, schedule, reason)` helper |
| `api/tests/workflows/test_schedule_lifecycle_cascade.py` | **NEW** — 8 cases: contact merge repoints; contact delete deactivates; orphan run marked errored; consecutive-20-empty deactivates + emails; orphan schedule cleanup finds workflow-less rows; email sent on manual pause but NOT on natural exhaustion; reaper honors org isolation; sweep continues after reaper finds nothing |

**~9 files, ~500 lines.**

## Plan

1. **Contact-merge repoint** — inside `merge_contacts_service`'s existing transaction, add `UPDATE tbl_workflow_schedules SET contact_id = :winner WHERE contact_id = :loser`. Audit event per repointed row. Test: create schedule on loser, merge, verify winner has it.
2. **Contact-delete deactivation** — same shape, in `delete_contact_service`. Audit + email.
3. **Orphan-run reaper** — added to `sweep_waits` after schedule dispatch. Uses `advisory_lock` on the reaper responsibility so multi-worker doesn't double-reap.
4. **Consecutive-empty counter** — send-action's audience-empty path calls the increment service; sweep dispatch reads before enrolment, deactivates + emails at 20.
5. **Weekly orphan-schedule sweeper** — new beat entry (once a week, e.g. Sunday 03:00 UTC); logs findings; does not auto-delete (safety) — writes a repair-report audit row.
6. **Email template** — Tailwind-styled HTML matching existing notification templates; includes deep link.
7. **Tests** — cover every branch in §In-scope.

## DB changes / migrations

None — Step 1's schema is sufficient. Only new beat task registration in celery config.

## Verification

- Create schedule with `contact_id = X`; merge X into Y; verify schedule now has `contact_id = Y` + audit row.
- Create schedule with `contact_id = X`; hard-delete X; verify schedule `active = false, deactivation_reason = 'contact_deleted'` + audit + email in dev inbox.
- Kill Celery worker mid-fire; wait 1 hour; verify pending run marked `errored` with `error_reason = 'orphaned_pending'`.
- Create schedule whose audience resolver always returns empty; wait 20 fires; verify deactivation + email.
- `SELECT * FROM tbl_workflow_schedules WHERE workflow_id NOT IN (SELECT id FROM tbl_workflows)` → weekly sweeper writes a repair-report on next Sunday tick.
- Pin-tests + ruff clean.

## Stop-and-report template

```
Step 6 done — contact-merge cascade + orphan reaper + empty-fire deactivation + weekly orphan sweeper.

Files changed: <list>
What you can verify:
  - Merge two contacts → schedule FK repoints atomically
  - Delete a contact → its schedules deactivate + owner emailed
  - Simulate sweep crash (kill worker mid-run) → orphan run marked errored after 1h
  - Force 20 consecutive audience_empty fires → schedule auto-off + owner emailed
  - `celery beat` shows new weekly `sweep_orphan_schedules_weekly` task
Tests added: 8
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean]
Awaiting your 'proceed' for Step 7.
```
