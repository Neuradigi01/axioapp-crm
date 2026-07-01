# Production test runbook — Google Calendar sync

**Purpose.** End-to-end smoke on Ajay's Workspace once Steps 1-5 are
deployed, using a real Google Account. This is what an ops team runs
after the first release lands in staging + production to confirm the
happy path works and the failure paths degrade gracefully.

**Target org.** `41f9ede9-41b3-44ce-b489-3004566d4068` (Ajay's Workspace),
Owner `ajaygogane224@gmail.com` — same one specified in the smoke-test
memory.

**Target Google account.** `ajaygogane224@gmail.com` (also added as a
test user in Google Cloud Console per
[`manual-google-calendar-setup.md`](manual-google-calendar-setup.md)
Step 5).

**Prerequisites.**

1. [`manual-google-calendar-setup.md`](manual-google-calendar-setup.md)
   Steps 1-4 completed (Calendar API enabled + scope added + redirect
   URI + test users).
2. All 5 shipping-step migrations applied
   (`0147_google_calendar_tokens` at DB head).
3. Celery worker running with `src.app.core.integrations.
   google_calendar.tasks` in the autodiscover list (added in Step 4).
4. Celery beat running (needed for the 30-min reconcile sweep step).
5. Frontend + API deployed with Step 5 UI live.

---

## Smoke — the 9-minute walkthrough

### 1. Connect from the Integrations page (1 min)

- Log in to the CRM as `ajaygogane224@gmail.com`.
- Nav to **Settings → Integrations** (`/user/integrations`).
- Expect: the "Google Calendar" card is visible between "Google Ads"
  and "Meta Ads". Right-side pill reads **Not connected**.
- Click **Connect**.
- Expect: the browser navigates to `accounts.google.com/o/oauth2/...`.
  Google's consent screen lists at least one calendar-related scope
  (something like "See, edit, share, and permanently delete all the
  calendars you can access using Google Calendar").
- Click **Continue** through the "This app isn't verified" prompt
  (expected in Testing mode) → grant.
- Expect: browser lands back on `/user/integrations?status=
  google_calendar_connected` → success banner appears + the card
  flips to **Connected**, showing "Connected as ajaygogane224@gmail.com".

**If Google shows `access_denied` "The scope is not allowed":**
Step 3 of `manual-google-calendar-setup.md` wasn't saved. Re-open
OAuth consent screen → Data Access → add `calendar.events`.

**If Google shows `redirect_uri_mismatch`:**
Step 4 of `manual-google-calendar-setup.md` is wrong. Copy the
exact URI from Google's error page into Credentials → Authorized
redirect URIs.

### 2. First appointment → event appears (30s)

- Nav to **Appointments** (`/user/appointments`).
- Click **New appointment**. Pick any contact, set the title to
  `Discovery — Runbook smoke`, schedule ~10 minutes into the future,
  assignee = Ajay. Save.
- Within ~5 seconds:
  - Flower (`crm-flower-1`, port 5555) shows one
    `src.app.core.integrations.google_calendar.tasks.sync_appointment`
    task fired + succeeded.
  - `tbl_appointments.google_calendar_event_id` is populated for this
    row (verify with `psql`).
- Open `calendar.google.com` in another tab (still logged in as
  Ajay) → the event **Discovery — Runbook smoke** is visible at the
  scheduled slot.
- Open the appointment popover in the CRM → header chip shows green
  **Synced ✓**.

### 3. Edit the appointment → event updates (30s)

- In the CRM, reschedule the appointment to +1 hour.
- Within ~5 seconds:
  - Flower shows a second sync task.
  - Google Calendar reflects the new time.
- Rename the appointment (e.g. append " v2").
- Same again — event title updates within seconds.

### 4. Reassign → old event deletes + new event lands (1 min)

- Reassign the appointment to a second employee who has ALSO
  connected their Google Calendar. (If you don't have one, connect
  `neuradigi01@gmail.com` from Step 4 of the manual setup — same test
  user.)
- Within ~5s: Flower shows **two** tasks — one for the old assignee
  (delete) + one for the new (create).
- Ajay's Google Calendar: the event disappears.
- The new assignee's Google Calendar: the event appears.

### 5. Reassign to an unconnected employee (1 min)

- Reassign back to Ajay OR to a third employee who has NOT connected
  Calendar.
- Within ~5s: Flower shows one delete task on the previous assignee,
  one no-op skip on the new (returns `"skipped"` in the task
  result).

### 6. Delete the appointment (30s)

- Delete the appointment in the CRM.
- Within ~5s: Flower shows one sync task returning `"deleted"`.
- Google Calendar: the event is gone.

### 7. Disconnect from the Integrations page (30s)

- Back to **Settings → Integrations** → Google Calendar card.
- Click **Disconnect**, confirm.
- Card immediately flips back to **Not connected** with a Connect
  button.
- Verify `tbl_user_google_calendar_tokens` no longer has a row for
  Ajay (`SELECT * FROM tbl_user_google_calendar_tokens WHERE
  google_email='ajaygogane224@gmail.com'` returns 0 rows).

### 8. Revoke upstream → row flips to `revoked` (2 min)

- Reconnect Google Calendar via the card.
- In another tab, go to
  `myaccount.google.com/permissions` → find the CRM app → click →
  **Remove access**. Google now considers the refresh token invalid.
- Back in the CRM, create a new appointment for Ajay.
- Within ~5s: Flower shows the sync task with a rate-limit or auth
  error. The row on `tbl_user_google_calendar_tokens` for Ajay
  flips to `status='revoked'`.
- Reload `/user/integrations` → the Google Calendar card shows the
  amber **Reconnect needed** state, with the error surfaced in the
  `last_error` field.
- Click **Reconnect** → the OAuth flow completes cleanly (fresh
  refresh token because `prompt=consent` forces it) → card flips
  back to green **Connected**.

### 9. Beat reconciliation sweep (up to 30 min wait)

- Stop the Celery worker:
  `docker compose stop celery`.
- Create an appointment for Ajay in the CRM. The
  `_dispatch_calendar_sync` helper's `try/except` catches the Redis
  publish failure silently — no event id gets stored.
- Verify: `tbl_appointments.google_calendar_event_id IS NULL` for
  the new row.
- Restart the Celery worker: `docker compose start celery`.
- Wait up to 30 min for the next `crontab(minute="*/30")` tick of
  `google-calendar-reconcile`.
- After the tick: Flower shows one `reconcile_pending` task fire →
  which dispatches a `sync_appointment` task per row → the event
  appears in Ajay's Google Calendar.

Alternatively: to skip the wait, trigger the beat task manually:
```bash
docker exec crm-celery-1 celery -A src.celery.worker.celery call \
    src.app.core.integrations.google_calendar.tasks.reconcile_pending
```

---

## Failure-path spot-checks

| Failure | What to do | Expected UX |
|---|---|---|
| Refresh token revoked upstream | Runbook step 8 | Card flips to Reconnect needed, `last_error` surfaced |
| Google API returns 500 | Simulate by pointing `oauth._TOKEN_URL` at an invalid host in a staging build | Task marks `last_error='GoogleCalendarBadResponse: ...'`, no retries beyond `max_retries=3` |
| Google rate limits | Simulated by returning 403 `userRateLimitExceeded` from the fake httpx client in unit tests | Celery `autoretry_for=(GoogleCalendarRateLimited,)` retries with 30s/60s/120s backoff, cap 10 min |
| Celery worker down | Runbook step 9 | Appointment writes still succeed; sync deferred until worker returns; beat sweep reconciles within 30 min |
| Redis down | Same as worker down | Same |
| DB down | Both writes fail; entire request 500s | Standard CRM failure surface |

---

## What "green" looks like

A green run means every step above finishes as documented within the
listed time budget. If any step takes longer than **~10 seconds** to
reflect on the Google side (excluding the intentional 30-min beat
wait in step 9), something's wrong — check:

1. Flower — is the task firing? Is it succeeding?
2. `crm-celery-1` docker logs — any Python tracebacks?
3. `SELECT status, last_error, last_synced_at
    FROM tbl_user_google_calendar_tokens
    WHERE google_email='ajaygogane224@gmail.com'`
   — is the row in a healthy state?
4. Google Cloud Console → APIs & Services → Google Calendar API →
   Quotas — hitting a quota?

Standard troubleshooting order: Flower → docker logs → DB row →
Cloud Console.
