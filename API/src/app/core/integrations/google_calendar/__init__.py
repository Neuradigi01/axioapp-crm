"""Per-user Google Calendar sync — one-way write (CRM → Google).

Track: ``tasks/google-calendar-sync/`` (v1). Every employee connects
their own Google account once via ``GET /api/v1/integrations/
google-calendar/authorize``; from that moment on every
:class:`core.appointments.models.Appointment` assigned to that user is
mirrored into their Google Calendar within seconds.

The module is intentionally SEPARATE from ``core/integrations/google/``:
that one owns the per-org Google Ads OAuth (one connection covers the
whole org's ad accounts). Google Calendar sync is fundamentally
per-user — each employee sees their own appointments in their own
calendar — so the token row is keyed on ``(org_id, user_id)`` rather
than ``(org_id, provider)``. Sharing an OAuth client between the two
is fine (see ``manual-google-calendar-setup.md``); sharing the *token
row* would be wrong.

Step 1 ships:

* :class:`models.GoogleCalendarToken` — the ORM binding for the new
  ``tbl_user_google_calendar_tokens`` table.

Subsequent steps layer on:

* Step 2 → ``oauth.py`` / ``router.py`` / ``service.py`` / ``data_access.py``
* Step 3 → ``api_client.py`` / ``sync_service.py`` / ``exceptions.py``
* Step 4 → ``tasks.py`` + hooks in ``core/appointments/service.py``
* Step 5 → frontend
* Step 6 → tests + operator docs
"""
