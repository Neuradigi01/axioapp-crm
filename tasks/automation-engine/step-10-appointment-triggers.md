# Step 10 — Appointment triggers (booked + reminders)

**Goal:** Publish `appointment.booked`, `appointment.reminder_24h`, `appointment.reminder_1h` events. Seed three default triggers per org so booking confirmation goes out instantly, and reminders fire 24h and 1h before the appointment. Daily scheduler scans upcoming appointments for the reminder events.
**Status:** Pending
**Depends on:** Steps 1-9 (engine + UI live). `core/appointments/` module (existing).

---

## Scope

In-scope:
- `core/events/event_catalog.py`: add three appointment events:
  - `appointment.booked` — fires when a new appointment row is created. Payload: `{appointment_id, org_id, contact_id, contact_snapshot, scheduled_at, location, notes}`.
  - `appointment.reminder_24h` — fires 24h before `scheduled_at`. Same payload.
  - `appointment.reminder_1h` — fires 1h before `scheduled_at`. Same payload.
- `core/appointments/service.py` (existing): after committing a new appointment row, call `events.publish("appointment.booked", payload, org_id=...)` with deterministic event_id `f"appointment_booked:{appointment_id}"`.
- `core/appointments/tasks.py` (new or extend):
  - Celery beat task `appointments.scan_for_reminders` — runs every 15 minutes. Scans `tbl_appointments` for rows whose `scheduled_at` falls in `[now+23.5h, now+24.5h]` and emits `appointment.reminder_24h` for each (deduped by event_id `f"appointment_reminder_24h:{appointment_id}"`). Same scan for the 1h window.
- `core/automation/seeds.py` extension:
  - `seed_appointment_booked_template` + `_trigger` — channel=WhatsApp by default (more immediate), falls back to email.
  - `seed_appointment_reminder_24h_template` + `_trigger` — channel=WhatsApp.
  - `seed_appointment_reminder_1h_template` + `_trigger` — channel=WhatsApp.
- Backfill migration `<ts>_seed_appointment_triggers_existing_orgs.py`.
- Tests: booking publishes; scheduler picks up upcoming appointments; idempotency on the scheduler re-runs.

Out of scope:
- Appointment reschedule / cancellation events — defer.
- Reminder customization beyond 24h + 1h (e.g., 1-week-out) — operator can clone and adjust.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | edit — register three appointment events |
| `API/src/app/core/appointments/service.py` | edit — publish appointment.booked |
| `API/src/app/core/appointments/tasks.py` | edit/new — scheduler scan |
| `API/src/app/core/automation/seeds.py` | edit — three new seeders |
| `API/src/app/core/tenants/service.py` | edit — call new seeders on org create |
| `API/alembic/versions/<ts>_seed_appointment_triggers_existing_orgs.py` | **NEW** — backfill |
| `API/tests/automation/test_appointment_triggers.py` | **NEW** |

**~7 files. ~450 lines.**

## Plan

0. **Data-access layer** (project convention): the reminder scanner reads from `tbl_appointments`. Put the windowed query in `core/appointments/data_access/appointments.py` as `find_due_for_reminder(window_start, window_end)` — NOT in the automation-engine's tasks.py (cross-module reads call the OWNING module's DAL). Create `core/appointments/data_access/` if it doesn't exist.
1. Catalog entries.
2. Publish call after appointment create.
3. Beat task scanner — windowed query for upcoming reminders.
4. Three new seeders for templates + triggers.
5. Backfill migration.
6. Tests: full chain — create appointment → instant booked event → after 23h+ wait → reminder event published → run fires.

## DB changes / migrations

One backfill migration only.

## Tests

7 pytest cases:
- `test_appointment_create_publishes_booked`
- `test_scheduler_picks_up_24h_window`
- `test_scheduler_picks_up_1h_window`
- `test_scheduler_does_not_double_fire_same_appointment` (event_id idempotency)
- `test_scheduler_skips_past_appointments`
- `test_all_three_seeds_idempotent`
- `test_disabled_seeded_trigger_skips_send`

## Smoke

```
1. POST /api/v1/appointments {contact_id, scheduled_at: now+25h, ...} → 200.
2. Audit log: appointment.booked event.
3. tbl_automation_runs: one row for "Appointment Booked" trigger → status=sent.
4. WhatsApp on the contact's phone: booking confirmation arrives.
5. Wait or advance clock 1.5h.
6. Beat scanner runs → appointment.reminder_24h published → run row written → WhatsApp delivers the 24h reminder.
7. Wait/advance to 1h before scheduled_at → 1h reminder fires similarly.
8. Disable "Appointment 1h Reminder" trigger → ensure subsequent appointments don't get the 1h reminder.
```

## Risks

- Beat scanner overlap: if Celery beat fires the scan twice during the 24h window, the second scan would re-publish. Event_id idempotency absorbs this.
- Time-zone correctness: `scheduled_at` stored UTC; reminder windows computed in UTC; renderers use the org's tz for display. Existing appointments module already handles this — no change needed here.

## Self-check (10 rules)

`core/appointments/` + `core/automation/seeds.py`. ✓ org_id propagated. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already registered. ✓ pack.yaml untouched. ✓ 7 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 10 — Appointment triggers (booked + reminders)
Files: 7
Verify: booking publishes; scheduler scans + publishes reminders; three seeded triggers active per org; existing orgs backfilled.
Tests: 7 pytest cases.
Awaiting "proceed".
```
