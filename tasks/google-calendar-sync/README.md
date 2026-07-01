# Google Calendar sync

**Manager spec 2026-06-30.** Every employee connects their own Google
Calendar to the CRM once. From that point on, every appointment they're
assigned to auto-syncs into their Google Calendar (Google side is
one-way write from the CRM for v1 — bi-directional sync is a follow-up
track once the operator side settles). Owners see their assignments in
their own calendar; sales reps see theirs; support agents see theirs.

Matches how HubSpot / Salesforce / Pipedrive / Zoho all handle it: **per-
user OAuth, per-user calendar, per-user connection status**.

---

## Why this track exists

Today the CRM stores appointments in `tbl_appointments` but they only
live inside the CRM UI. Employees have to context-switch between the CRM
and Google Calendar to see their own day. This track closes that gap:

- Every appointment assigned to a rep → auto-creates a calendar event
  in their Google Calendar within 5 seconds
- Rescheduling / editing in the CRM → PATCHes the calendar event
- Cancelling / unassigning in the CRM → DELETEs the calendar event
- **v1 is one-way write from the CRM.** Edits in Google Calendar do
  NOT propagate back — the CRM stays the source of truth. Bi-
  directional sync (Google push notifications → CRM update) is a v2
  follow-up.

## Scope for v1 (this track)

**In scope:**

- Per-user Google OAuth flow (extends the existing Ads OAuth patterns —
  new scope `https://www.googleapis.com/auth/calendar.events`).
- Encrypted per-user refresh-token storage.
- Google Calendar API client (create + update + delete events).
- Sync hook in `core/appointments/service.py` — after every CRUD, fire
  a Celery task that reconciles the calendar event for the assignee.
- Idempotency: the CRM stores the Google `event_id` on the appointment
  row so retries never create duplicates.
- Frontend: Integrations page card + per-user Connect button;
  per-appointment "Synced to Google Calendar ✓" badge on the
  appointment detail page.

**Out of scope (v2 track later):**

- Bi-directional sync (Google push notifications → CRM writes back).
  Requires Google's `watch` API + a public webhook receiver + conflict-
  resolution on both-sides-edited events. Doubles the surface.
- Microsoft Outlook / Office365 calendar sync. Same pattern, different
  OAuth provider — belongs in its own track.
- Multi-calendar picker (employee picks WHICH of their Google calendars
  to sync into). v1 syncs into their **primary** calendar.
- Attendee response tracking (accepted / declined pulled back into the
  CRM). Out for v1.

## Track structure

| Step | Title | Status | Files |
|---|---|---|---|
| 1 | [Schema + per-user token storage](step-1-schema-and-oauth-storage.md) | **COMPLETED** | 4 |
| 2 | [Per-user OAuth flow (Google Calendar scope)](step-2-oauth-flow-per-user.md) | **COMPLETED** | 6 |
| 3 | [Calendar API client + sync service](step-3-calendar-api-client-and-sync-service.md) | **COMPLETED** | 4 |
| 4 | [Appointment hooks + Celery task](step-4-appointment-hooks-and-celery-task.md) | **COMPLETED** | 4 |
| 5 | [Frontend Connect + badges](step-5-frontend-connect-and-badges.md) | **COMPLETED** | 7 |
| 6 | [Tests + docs](step-6-tests-and-docs.md) | **COMPLETED** | 3 |

**Total: 6 steps, 28 files, ~3 days of work.** ✅ **Track shipped.**

## Google Cloud setup (one-time, operator-side)

Before Step 2's smoke test works you need to enable the Calendar API on
the existing OAuth client in the shared Google Cloud project:

1. Go to `https://console.cloud.google.com/apis/library`
2. Search "Google Calendar API" → click Enable
3. On the OAuth consent screen, add scope:
   `https://www.googleapis.com/auth/calendar.events`
4. If the OAuth consent screen is still in "Testing" mode, add every
   employee's Gmail as a test user (Google's requirement for unverified
   apps).

Docs: `manual-google-calendar-setup.md` inside this folder (Step 2
ships it).

## Locked design decisions

- **Per-user, not per-org.** Each employee's calendar tokens live on
  `tbl_user_google_calendar_tokens (org_id, user_id, refresh_token,
  ...)`. Org-level Google Ads OAuth (`tbl_integrations`) is a separate
  concern.
- **One-way v1.** CRM writes to Google. Editing an event in Google
  Calendar does NOT propagate back. Documented in the UI (small
  "one-way sync" chip on the connection card).
- **Idempotent event IDs.** `tbl_appointments.google_calendar_event_id`
  stores the created event id so re-runs never dupe. Google's ETag is
  stored too so we can send `If-Match` on PATCH and detect drift.
- **Sync via Celery**, not inline. Appointment CRUD returns immediately;
  the sync task runs async so a 500ms Google API blip doesn't slow the
  CRM UX. Failure retry is exponential (max 3 attempts).
- **Encryption at rest.** Refresh tokens go into the same `Fernet`
  envelope as the Ads OAuth flow uses.

## Risks

- **Google API quota.** Default free quota is ~1M calls/day, plenty for
  a small operator. If an org has hundreds of employees each with
  hundreds of appointments/day, we might hit rate limits — add a
  per-user backoff in Step 4's Celery task.
- **Timezone handling.** `tbl_appointments.start_at` is timestamptz;
  Google Calendar event `start.dateTime` also carries a timezone. Push
  the appointment's timezone through (never let it default to UTC or
  the assignee sees wrong times).
- **Token revocation drift.** If an employee revokes access at
  accounts.google.com, our refresh call fails with `invalid_grant`.
  Handler: mark the row disconnected, surface a banner, don't
  auto-retry. Operator reconnects.

## What "done" looks like

An operator in Ajay's Workspace can:
1. Go to `/user/integrations` → click Connect on the Google Calendar
   card → OAuth grant → back at the CRM the card shows "Connected"
   with their Gmail address.
2. Create an appointment assigned to themselves → within 5s the event
   appears in their Google Calendar with the right title, time,
   attendees, location.
3. Edit the appointment title in the CRM → within 5s the calendar
   event's title updates.
4. Delete the appointment → the calendar event disappears.
5. Reassign the appointment to a different employee → the old event is
   deleted from the old assignee's calendar, a new event is created in
   the new assignee's calendar.
