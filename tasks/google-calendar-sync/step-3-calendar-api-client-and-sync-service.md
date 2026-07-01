# Step 3 — Calendar API client + sync service

**Goal:** Translate a CRM `Appointment` into Google Calendar `Event`
CRUD calls. Idempotent, retry-safe, timezone-correct.
**Status:** COMPLETED
**Depends on:** Step 2 (OAuth flow — provides `get_valid_access_token`).

---

## Scope

### API client — `google_calendar/api_client.py`

Thin async wrapper over Google Calendar API v3 endpoints. `httpx.AsyncClient`.

```python
async def create_event(
    session, *, user_id, calendar_id, event_body: dict
) -> tuple[str, str]:
    """Returns (event_id, etag). Raises GoogleCalendarError on 4xx/5xx."""

async def patch_event(
    session, *, user_id, calendar_id, event_id, event_body: dict,
    etag: str | None,
) -> tuple[str, str]:
    """Uses If-Match on the ETag when present so simultaneous edits
    from Google raise 412 instead of silently overwriting."""

async def delete_event(
    session, *, user_id, calendar_id, event_id,
) -> None:
    """DELETE + 204. 404 is treated as success (idempotent delete)."""

async def get_primary_calendar_id(
    session, *, user_id,
) -> str:
    """One-shot call to `/users/me/calendarList/primary` — cached on
    the token row after first call so it's not repeated per event."""
```

Common errors are mapped to typed exceptions:
- 401 → `GoogleCalendarTokenExpired` (caller refreshes + retries once)
- 403 (rate-limit) → `GoogleCalendarRateLimited` (Celery task backs off)
- 404 → `GoogleCalendarEventGone` (drop the CRM's stored event_id + move on)
- 412 → `GoogleCalendarConcurrencyConflict` (event edited in Google
  since our last read — v1 refuses to overwrite; logs to
  `last_error` for the operator to reconcile)

### Sync service — `google_calendar/sync_service.py`

The high-level layer the Celery task calls:

```python
async def sync_appointment(
    session, *, appointment_id, user_id
) -> str:
    """Reconciles the Google Calendar event for one appointment. Returns
    a summary string ('created' / 'updated' / 'deleted' / 'skipped')."""
```

Decision tree:

```
Fetch appointment + fetch user's token row
├─ Token row missing / status != 'active'   → skip, log
├─ Appointment deleted OR unassigned         →
│    if appointment.google_calendar_event_id set → DELETE it, null out
│    else                                        → skip
├─ Appointment exists + no event_id          → CREATE, store event_id + etag
└─ Appointment exists + event_id present      → PATCH, refresh etag
```

Event body translation:

```python
{
  "summary": appointment.title,
  "description": appointment.description + f"\nCRM appointment: {url}",
  "location": appointment.location,
  "start": {"dateTime": start_at.isoformat(), "timeZone": org.timezone},
  "end": {"dateTime": end_at.isoformat(), "timeZone": org.timezone},
  "attendees": [
    {"email": contact.email, "displayName": contact.full_name}
    for contact in appointment.attendees if contact.email
  ],
  "reminders": {"useDefault": True},
  # Metadata Google shows in the event details — helpful for debug.
  "extendedProperties": {
    "private": {
      "crm_appointment_id": str(appointment.id),
      "crm_org_id": str(appointment.org_id),
    },
  },
}
```

### Reassignment special case

If an appointment's `assigned_to_id` changes:
1. Old assignee's calendar → DELETE the old event
2. Null out the appointment's `google_calendar_event_id` + etag
3. New assignee's calendar → CREATE a new event (only if they've
   connected Calendar; otherwise skip)

Handled inside `sync_appointment` by comparing the appointment's
current `assigned_to_id` to whatever `user_id` owns the stored
`google_calendar_event_id` (traced via a small helper).

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/google_calendar/api_client.py` | **NEW** |
| `API/src/app/core/integrations/google_calendar/sync_service.py` | **NEW** |
| `API/src/app/core/integrations/google_calendar/exceptions.py` | **NEW** — typed errors |
| `API/src/app/core/integrations/google_calendar/service.py` | edit — expose `mark_row_error`, `mark_row_synced` for the sync task |

**~4 files, ~450 lines.**

## Verify

Unit tests + one manual smoke:

1. `sync_appointment` on a fresh appointment → returns 'created', DB
   row now has `google_calendar_event_id` + `google_calendar_etag`
2. Second call → returns 'updated' (PATCH)
3. Delete the appointment locally, re-run sync → 'deleted', DB row's
   event_id nulled out
4. Simulate 401 from Google → the `get_valid_access_token` refresh
   path fires, second attempt succeeds
5. Simulate 412 → status marked with `last_error='concurrency_conflict'`,
   no overwrite

## Self-check

DAL wraps ORM writes. Sync service commits per-appointment (short txn).
API client is stateless. No retry loop inside the client (Celery task
handles retries). Timezone piped through from `org.timezone`.
Stop-report.
