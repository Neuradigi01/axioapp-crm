# Step 1 — Schema + per-user OAuth token storage

**Goal:** Add the DB shape that stores each user's Google Calendar
connection state. Two tables: per-user tokens + per-appointment
Google-side identifiers so we can PATCH / DELETE the right event.
**Status:** Pending
**Depends on:** Nothing (foundation step).

---

## Scope

### New table — `tbl_user_google_calendar_tokens`

One row per `(org_id, user_id)`. Holds the encrypted refresh token +
enough metadata to render "Connected as ajay@gmail.com" on the
integrations card.

Columns:
- `id` UUID PK
- `org_id` UUID FK → `tbl_organizations.id`
- `user_id` UUID FK → `tbl_users.id`  UNIQUE per org
- `google_email` TEXT — display label on the integrations card
- `google_user_id` TEXT — Google's stable `sub` claim
- `refresh_token_encrypted` TEXT — Fernet-encrypted
- `access_token_encrypted` TEXT nullable — cached until expiry
- `access_token_expires_at` TIMESTAMPTZ nullable
- `scopes_granted` TEXT[] — what the user actually approved
- `primary_calendar_id` TEXT — usually the user's email; captured on
  first sync
- `status` TEXT — `active` / `revoked` / `error`
- `last_error` TEXT nullable — surfaced on the integrations card
- `last_synced_at` TIMESTAMPTZ nullable
- `connected_at`, `updated_at` TIMESTAMPTZ

Constraint: `UNIQUE (org_id, user_id)` — one active connection per
user per org.

RLS: `org_id = current_setting('app.current_org_id')` — same convention
as every other tenant-scoped table.

### Extend `tbl_appointments`

Two nullable columns so the sync task knows what Google-side entity to
update / delete:

- `google_calendar_event_id` TEXT — Google's event id (returned on
  create)
- `google_calendar_etag` TEXT — Google's ETag; used for optimistic
  concurrency on PATCH

Both nullable — appointments that haven't been synced yet (or whose
assignee never connected Calendar) leave them NULL.

### Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_google_calendar_tokens.py` | **NEW** |
| `API/src/app/core/integrations/google_calendar/__init__.py` | **NEW** — module skeleton |
| `API/src/app/core/integrations/google_calendar/models.py` | **NEW** — `GoogleCalendarToken` ORM |
| `API/src/app/core/appointments/models.py` | edit — 2 new columns |

**~4 files, ~180 lines.**

## Verify

- `docker exec crm-api-1 alembic upgrade head` → new revision applies
  cleanly, downgrade reverses
- `SELECT column_name FROM information_schema.columns WHERE
  table_name='tbl_user_google_calendar_tokens'` returns the 13 columns
- `\d tbl_appointments` shows the 2 new nullable columns

## Self-check

`core/integrations/google_calendar/` + tiny extension to appointments.
org_id-scoped. RLS on the new table. No pack imports. No custom fields.
Stop-report.
