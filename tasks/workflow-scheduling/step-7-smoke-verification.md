# Step 7 — Smoke verification on Ajay's Workspace

**Goal:** End-to-end validation of every locked decision from the README against a real org. All manual, browser-driven, using the org the manager watches (Ajay's Workspace, per memory).

**Status:** Pending

**Depends on:** Steps 1–6 (full stack deployed)

---

## Scope

**In-scope:**
- Manual smoke matrix (browser + psql/curl backups) against **Ajay's Workspace** (org `41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`, per memory).
- Every preset kind fired at least once.
- DST edge case validated (may need to fake tz or use a schedule with next fire computed inside a DST transition; simulate via psql `UPDATE next_run_at`).
- Beat-outage skip validated (stop Celery beat, wait past a fire, restart, verify one fire + `schedule.missed_fire` audit).
- Contact-merge repoint validated end-to-end.
- Two-tab edit → 409 conflict validated.
- 501st schedule → cap error validated.
- Advanced cron validated.
- One results doc in this folder: `SMOKE-RESULTS.md` with pass/fail per row.

**Out-of-scope:**
- Load testing (separate track).
- Provider-side WhatsApp/Email verification (send templates fire; provider inspection is a different concern).

## Smoke matrix (each = 1 checklist row in `SMOKE-RESULTS.md`)

| # | Case | How | Expected |
|---|---|---|---|
| 1 | Create Once schedule on a seeded workflow | Builder → detail → Add schedule → Once → 5 min from now | Fires within 6 min; run row with `trigger_kind='schedule'`; schedule row `active=false, deactivation_reason='max_runs'` |
| 2 | Create Daily schedule with tz = Asia/Kolkata | Same workflow, Daily 15:00 IST | `next_run_at` in DB stored as `09:30 UTC` |
| 3 | Create Weekly schedule (Mon+Wed 09:00) | | Preview shows next Mon + Wed at 09:00 local |
| 4 | Create Monthly schedule on day 31 | Any workflow, Monthly 31st 09:00 | Next fire in Feb clamps to 28/29 |
| 5 | Create Custom Interval every 10 min | Any workflow, interval | Fires every 10 min; visible run rows |
| 6 | Advanced cron `0 9 * * 1` | Any workflow | Preview shows next 5 Mondays 09:00 |
| 7 | Attempt cron `* * * * *` | | 422 "minimum inter-fire interval is 5 minutes" |
| 8 | Attempt interval = 2 min | | 422 "minimum interval is 5 minutes" |
| 9 | Attempt `starts_at` = yesterday | | 422 "start time is in the past" |
| 10 | Attempt `end_at` < `starts_at` | | 422 "end time must be after start time" |
| 11 | Create 500 schedules, attempt 501st | psql-scripted seed + one UI POST | 422 cap error |
| 12 | Attempt cross-org POST (Ajay tokens against another org's workflow) | curl | 404, no leak |
| 13 | Attempt PATCH without `If-Match` | curl | 428 |
| 14 | Two-tab edit conflict | Two browser tabs on same schedule | Second save shows 409 toast |
| 15 | Multiple schedules on same workflow | Add 2 schedules to one workflow | Both visible in panel; both fire independently |
| 16 | Schedule on a seeded event-triggered workflow | Pick "Birthday Wish" workflow; add Weekly Mon 09:00 | Both `contact.birthday` events AND Monday schedules fire runs; no interference |
| 17 | Beat-outage skip | `docker exec ... systemctl stop celery-beat` for 15 min then restart | On restart: one fire + `schedule.missed_fire` audit event with count=1 |
| 18 | On-missed = backfill_all | Create schedule with backfill_all; stop beat 30 min; restart | 6 fires enqueued (one per 5-min slot); rate-limit honored |
| 19 | Concurrency forbid | Schedule with 5-min interval, workflow has 15-min wait node | Second fire skipped while first still running; audit event |
| 20 | Concurrency replace | Same setup, replace policy | First run canceled when second fires |
| 21 | Pause + resume | UI pause schedule, wait a fire cycle, resume | Paused: no fires. Resume: `next_run_at` recomputed forward |
| 22 | Contact merge repoints schedule | Create schedule with contact_id=X; merge X→Y | Panel shows contact_id updated; audit row present |
| 23 | Contact delete deactivates schedule | Delete contact X | Schedule deactivated, reason=contact_deleted, owner email received |
| 24 | Malformed cron via psql | `UPDATE tbl_workflow_schedules SET config_json='{"cron":"bogus"}' WHERE id=...` | Next sweep: row auto-deactivates, reason=recurrence_invalid, sweep continues (other rows fire) |
| 25 | Null-contact action safety | Schedule (contact_id=NULL) → workflow with `send.email` node (requires contact) | Run marks errored with `error_reason='ActionRequiresContactError:send.email'`; schedule keeps advancing |
| 26 | 20 consecutive empty fires deactivate | Schedule + workflow whose send resolves to no recipient always | After 20 fires: deactivated, reason=consecutive_empty, owner email |
| 27 | UI rollback: pause everything | For safety at end of smoke | All test schedules paused; no lingering fires |

## Files to touch

| File | Action |
|---|---|
| `tasks/workflow-scheduling/SMOKE-RESULTS.md` | **NEW** — matrix with pass/fail per row + timestamps + screenshots links |
| Memory update | If any non-obvious quirk surfaced (e.g. specific tz gotcha, celery-beat restart timing), save as a feedback memory |

**~2 files.** No production code.

## Plan

1. Freeze code (no commits during smoke).
2. Deploy Steps 1–6 to a fresh dev DB replica of Ajay's Workspace (or use the workspace directly with test workflows tagged for cleanup).
3. Walk rows 1–26 in order; capture screenshots per row.
4. Row 27 last — pause every test schedule to leave the org clean.
5. Fill `SMOKE-RESULTS.md`; mark each row pass/fail with a link to evidence.
6. If any row fails: create a bug entry in the results doc; the track does not ship until all rows pass or manager waives.

## Verification

- All 26 rows pass (or waived).
- Row 27 executed; org left clean.
- Any new memory items saved.
- Report ready for manager sign-off.

## Stop-and-report template

```
Step 7 done — smoke verification.

Files changed: SMOKE-RESULTS.md
What you can verify:
  - Open `tasks/workflow-scheduling/SMOKE-RESULTS.md` for pass/fail matrix
  - Ajay's Workspace has no residual test schedules (row 27 confirms)
Tests added: 26 manual (not pytest — human-verified against a real org)
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean]

Track complete. Ready for manager sign-off.
```
