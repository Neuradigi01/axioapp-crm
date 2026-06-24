# Step 12 — Time-based triggers (birthday, stale-lead)

**Goal:** Add a daily scheduler that publishes time-anchored events: `contact.birthday` (every contact whose `date_of_birth` matches today), `lead.stale_30d` (every lead with no activity in 30 days). Seed default triggers so an org gets birthday wishes + stale-lead nudges out of the box.
**Status:** Pending
**Depends on:** Steps 1-11. `core/contacts/` (for date_of_birth field), `core/activities/` (for last-activity timestamps).

---

## Scope

In-scope:
- `core/events/event_catalog.py`:
  - `contact.birthday` — fires once per contact per year on their birthday (org tz). Payload: `{contact_id, org_id, contact_snapshot, age_turning}`.
  - `lead.stale_30d` — fires once per lead when 30 days have elapsed without activity. Payload: `{lead_id, org_id, contact_id, contact_snapshot, days_since_last_activity, last_activity_at}`.
- `core/automation/scheduler.py`:
  - `scan_birthdays(now_utc)` — queries contacts where `EXTRACT(MONTH FROM date_of_birth) = EXTRACT(MONTH FROM now in org_tz)` AND same for day. For each: publish `contact.birthday` with event_id `f"contact_birthday:{contact_id}:{year}"`.
  - `scan_stale_leads(now_utc)` — queries `tbl_leads` with no activity in the last 30 days, status NOT in (`won`, `lost`, `archived`). For each: publish `lead.stale_30d` with event_id `f"lead_stale_30d:{lead_id}:{first_stale_date}"` so it fires once (not daily).
- `core/automation/tasks.py`:
  - Celery beat task `automation.daily_time_based_scan` — runs once per day at the configured time (default 8am org tz).
- `core/automation/seeds.py` extension:
  - `seed_contact_birthday_template + _trigger` — channel=WhatsApp by default (more personal); body uses `{{contact.first_name}}` + birthday wishes.
  - `seed_lead_stale_30d_template + _trigger` — channel=email; "Still interested? Let me know if I can help." with the assigned salesperson's signature.
- Backfill migration: seeds for existing orgs.
- Birthday timezone fairness: each org runs the scan in its own tz (default Asia/Kolkata).

Out of scope:
- Anniversary triggers (e.g., contact anniversary of becoming a customer) — defer.
- Stale-lead nudges at intervals beyond 30d (60d, 90d) — operator can clone + adjust delay.
- Date-of-birth field migration on contacts — assumed already present per `core/contacts/` schema; verify and add a column if missing as a sub-step.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | edit — register two events |
| `API/src/app/core/automation/scheduler.py` | **NEW** — daily scan logic |
| `API/src/app/core/automation/tasks.py` | edit — daily beat task |
| `API/src/app/core/automation/seeds.py` | edit — two new seeders |
| `API/src/app/core/tenants/service.py` | edit — call new seeders |
| `API/alembic/versions/<ts>_seed_time_based_triggers_existing_orgs.py` | **NEW** |
| `API/tests/automation/test_time_based.py` | **NEW** |

**~7 files. ~450 lines.**

## Plan

1. Catalog entries.
2. Scheduler: pure queries returning lists of (event_type, payload) tuples. Decoupled from the publisher so testable in isolation.
3. Beat task: invokes scheduler per org tz, then publishes each event.
4. Seeders + tenants service hook.
5. Backfill migration.
6. Tests: birthday scan finds today's birthdays only; stale-lead scan respects status filter; idempotency on repeated daily scans.

## DB changes / migrations

One backfill migration. Schema unchanged (assumes `tbl_contacts.date_of_birth` and `tbl_leads.last_activity_at` exist).

## Tests

8 pytest cases:
- `test_birthday_scan_finds_today_only`
- `test_birthday_scan_skips_no_birthday`
- `test_birthday_event_id_includes_year` (idempotency across years)
- `test_stale_lead_scan_finds_30d_inactive`
- `test_stale_lead_scan_skips_won_lost_archived`
- `test_stale_lead_event_id_is_first_stale_date` (so daily scans don't refire)
- `test_seeders_idempotent`
- `test_daily_beat_task_calls_scheduler_per_org_tz`

## Smoke

```
1. Set a test contact's date_of_birth to today (in YYYY-MM-DD format, year ignored).
2. Manually trigger the daily beat task.
3. Audit log: contact.birthday event for that contact.
4. WhatsApp on their phone: birthday message arrives.
5. Re-run the beat task in the same day → no second event (event_id deduped).
6. Create a lead with last_activity_at = now-31d, status=qualified.
7. Trigger beat task → lead.stale_30d event publishes → email sent.
8. Run again next day → no second fire (event_id keyed on first-stale date).
```

## Risks

- Birthday scan running multiple times in a day (Celery worker restart, etc.) — idempotency relies on event_id including the year. Verified in test.
- Stale-lead definition: "no activity in 30 days" means no tbl_activities rows in 30d. If the org's activity tracking is sparse, false positives possible. Documented; operator can tighten the condition via the trigger's conditions JSONB.
- DOB timezone sensitivity — a contact in IST vs the org's tz could create a 1-day-off birthday. Scan uses the org's tz; if a contact has their own preferred tz (rare), that's a future enhancement.

## Self-check (10 rules)

`core/automation/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already registered. ✓ pack.yaml untouched. ✓ 7 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 12 — Time-based triggers (birthday, stale-lead)
Files: 7
Verify: daily scan finds birthdays + stale leads; events publish; seeded triggers fire; existing orgs backfilled.
Tests: 8 pytest cases.
Awaiting "proceed".
```
