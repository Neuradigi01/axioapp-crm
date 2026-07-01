"""Typed exceptions raised by the Google Calendar API client + sync
service.

Split so callers (Celery task, sync service) can react appropriately:

  * :class:`GoogleCalendarTokenExpired`   — 401 from Google. The API
    client's own refresh path already tried; the caller should
    surface the underlying auth issue (usually revoked upstream).
  * :class:`GoogleCalendarRateLimited`    — 403 with a `userRateLimitExceeded`
    reason. Celery task catches + retries with exponential backoff.
  * :class:`GoogleCalendarEventGone`      — 404. Event was deleted in
    Google Calendar since we last stored the id. The sync path drops
    the CRM's stored id + treats the appointment as "never synced"
    so the next reconciliation recreates it.
  * :class:`GoogleCalendarConcurrencyConflict` — 412 (If-Match mismatch).
    v1 policy: don't overwrite Google-side edits; mark the token row
    ``last_error='concurrency_conflict'`` so the operator sees it +
    can decide whether to force-sync via a manual retry endpoint (v2).
  * :class:`GoogleCalendarBadResponse`    — any other 4xx/5xx we can't
    classify. Sync task retries a few times, then surfaces on the
    token row.
  * :class:`GoogleCalendarError`          — parent class the sync loop
    catches for logging.
"""

from __future__ import annotations


class GoogleCalendarError(Exception):
    """Base for every recoverable-or-diagnosable Google Calendar API
    failure. The sync task catches this parent in its outer try/except
    and logs + surfaces on the token row."""


class GoogleCalendarTokenExpired(GoogleCalendarError):
    """401 from Google after we already refreshed. Usually means the
    refresh_token was revoked upstream — the token row should be
    marked ``status='revoked'`` and the operator prompted to
    reconnect via the integrations card."""


class GoogleCalendarRateLimited(GoogleCalendarError):
    """403 with a rate-limit reason (userRateLimitExceeded /
    rateLimitExceeded / quotaExceeded). Celery task's
    ``autoretry_for=(GoogleCalendarRateLimited,)`` catches this + backs
    off exponentially."""


class GoogleCalendarEventGone(GoogleCalendarError):
    """404 on PATCH / DELETE. The event was removed in Google Calendar
    since we stored its id. Sync path treats as "never synced" — drops
    the local event_id + recreates on the next pass."""


class GoogleCalendarConcurrencyConflict(GoogleCalendarError):
    """412 Precondition Failed on PATCH — the ``If-Match`` ETag we sent
    doesn't match Google's current ETag. Someone edited the event on
    the Google side since our last read. v1 refuses to overwrite; the
    conflict surfaces on the token row's ``last_error``."""


class GoogleCalendarBadResponse(GoogleCalendarError):
    """Any 4xx/5xx we can't classify more specifically, or a 2xx with a
    malformed body (missing ``id`` on create, non-JSON, etc.). The
    Celery task retries a few times, then gives up + surfaces the
    error text."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


__all__ = [
    "GoogleCalendarBadResponse",
    "GoogleCalendarConcurrencyConflict",
    "GoogleCalendarError",
    "GoogleCalendarEventGone",
    "GoogleCalendarRateLimited",
    "GoogleCalendarTokenExpired",
]
