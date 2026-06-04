# Update Appointments page

A focused track to bring `/user/appointments` (list + calendar) up to standard-CRM expectations: status transitions (Scheduled / Completed / No-show / Cancelled), last-activity sort, owner column / owner-color on the calendar, reassign (single + bulk), reschedule modal, and row ergonomics (tel / WhatsApp on the linked contact). Reuses the shared primitives from [update-contacts-page/](../update-contacts-page/).

## Why this exists

Appointments already has `assigned_to_id` and a `status` field on the model, but the UI is still v1:

- **No `last_activity_at`** — same gap.
- **No status column / status filter** on the list. No status transition buttons.
- **No owner-color on the calendar** — you can't tell at a glance which appointments belong to Anita vs Rahul.
- **No reassign UI** — column exists, no pencil / no bulk transfer.
- **No reschedule modal** — changing the time requires a full edit modal.
- **No tel / mailto / WhatsApp** on the linked contact's phone / email.
- **Filters are basic** — no assignee dropdown, no scope toggle.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **`last_activity_at` column + sort** | Same denormalisation. Dispatch dict extended to include `appointment`. |
| **Status column + workflow buttons** | Scheduled / Completed / No-show / Cancelled pills. Row-level "Mark completed," "Mark no-show," "Cancel." |
| **Status filter chips** | All · Upcoming · Completed · No-show · Cancelled. |
| **Owner column + assignee filter + scope toggle** | "All / Team / Mine" preset. |
| **Calendar view owner-color** | Each event coloured by assignee (palette assigned deterministically by user id). |
| **Single + bulk reassign** | `ReassignModal` + `BulkActionBar`. New permission key `appointments.reassign`. |
| **Reschedule modal** | Standalone modal — date / time picker + optional reason — without opening the full edit form. |
| **Row ergonomics** | tel / mailto / WhatsApp on linked contact's phone / email; URL state; styled confirm cancel. |

## What this does NOT do

- Does not add **availability conflict detection** (depends on staff calendar integration; separate track).
- Does not add **recurring appointments** (out of scope for v1).
- Does not add **video-call link generation** (Google Meet / Zoom integration is a separate track).
- Does not add **email / SMS reminders to the customer** (Step 6 ships emails to *internal staff* who own the appointment; customer-facing reminders live in the campaigns / customer-comms modules and are a separate track).
- Does not add **push notifications (FCM / web-push)** — the channel enum and per-user preference already exist, but no FCM sender is wired. Deferred to a future `tasks/notifications-push-channel/` track.
- Does not add CSV export.

## Acceptance criteria

A Store Manager on `/user/appointments`:

1. Sees **Status column** with coloured pills.
2. Sees **Owner column** with the assigned staff.
3. Sees **Last activity** column with relative time.
4. Can filter by **Status chips** + **Assignee dropdown** + **Scope toggle (My / Team / All)**.
5. Switches to **Calendar view** — events coloured by Owner.
6. Clicks an event → small popover with Reassign / Reschedule / Mark completed / Cancel actions.
7. Can select rows and **bulk reassign** or **bulk cancel**.
8. Phone / email of the linked contact are **click-to-call / mailto / WhatsApp**.
9. **URL reflects filters** — refresh-safe.
10. **Junior staff** sees no reassign / no bulk-cancel buttons (gated).

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: `last_activity_at` + sort/filter + status transitions guarded + `appointments.reassign` | Pending | ~½ day |
| 2 | Frontend list + calendar: Owner / Status / Last activity + owner-color + scope toggle | Pending | ~½ day |
| 3 | Reschedule modal + bulk reassign + row ergonomics | Pending | ~½ day |
| 4 | [Assignee picker in Book Appointment modal](step-4-assignee-picker-book-modal.md) (users-list API wire-up) | COMPLETED | ~½ day |
| 5 | [In-app notifications on appointment events](step-5-in-app-notifications.md) (`appointment.assigned`/`rescheduled`/`cancelled`) | Pending | ~½ day |
| 6 | [Email channel opt-in](step-6-email-channel-opt-in.md) + Settings UI toggles | Pending | ~½ day |

**Total: ~3 working days.** Stop and report after each per Rule 9.

Steps 4–6 added 2026-06-04 — when QA-ing the booking flow, Owner could not pick another team member as assignee (modal hardcoded current user), and nobody was getting notified that an appointment had been booked for them. Three small additions close the multi-user appointment loop end-to-end (assignee → in-app + optional email).

## Dependencies

- [update-contacts-page/](../update-contacts-page/) — REQUIRED.
- Phase 2 appointments module — Done.
- Activities service hook — dispatch dict extended to include `appointment`.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 new migration (`0055_appointments_last_activity.py`), 4 modified (`appointments/models.py`, `schemas.py`, `service.py`, `router.py`), 1 modified (`activities/service.py` dispatch). | |
| Step 2 frontend | 3 modified (`appointments-api.service.ts`, `appointments.page.ts/html`). + 1 new (`shared/owner-color.util.ts`) — deterministic palette from user id. | |
| Step 3 frontend | 1 new (`reschedule-modal.component.ts/html`), 2 modified (`appointments.page.ts/html` for bulk + URL state + tel/wa). | |
| Step 4 frontend | 2 modified (`book-appointment-modal.component.ts/html`). | Pure UX wire-up. |
| Step 5 backend | 3 modified (`appointments/service.py`, `notifications/service.py`, `permissions/role_templates.py`). | Cross-module integration; no schema. |
| Step 6 backend + frontend | 1 new (`notifications/email_renderer.py`), 3 modified (`notifications/service.py`, `notification-preferences-tab.component.ts/html`). | Uses existing SMTP backend. |
| Tests | `tests/core/appointments/test_status_transitions.py` (Step 1), `test_notifications_emitted.py` (Step 5), `test_email_channel_appointment.py` (Step 6). | |

**Total ~22 files across 6 steps.**

## Self-check vs the 10 rules

- ✅ Rule 1, 5, 7 — `core/appointments/` untouched at boundaries.
- ✅ Rule 6 — `appointments.reassign` registered.
- ✅ Rule 8 — ≤10 files per step.
- ✅ Rule 10 — reschedule + status transitions ship complete.

## After this track

- Appointments page works as a real calendar / list worklist.
- Pattern of status pill + row buttons + owner-color now used everywhere a status field exists.
- **Multi-user booking loop is closed:** Owner can pick any staff member as assignee, and that staff member is notified (in-app always, email if they've opted in via Settings). Push channel reserved for a separate mobile-focused track.
- The `core/notifications/email_renderer.py` becomes the home for any future per-type email template — leads, walk-ins, tasks all get the same opt-in machinery for free.
