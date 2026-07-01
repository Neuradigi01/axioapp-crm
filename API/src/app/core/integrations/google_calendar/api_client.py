"""Thin async wrapper over Google Calendar API v3.

Four operations we need for one-way appointment sync:

  * :func:`create_event` — POST an event body, returns ``(event_id, etag)``.
  * :func:`patch_event`  — PATCH an existing event; optional ``If-Match``
    ETag so simultaneous edits raise 412 instead of silently overwriting.
  * :func:`delete_event` — DELETE an event; 404 is treated as success
    (idempotent).
  * :func:`get_primary_calendar_id` — one-shot lookup so the sync
    service can cache the user's primary calendar id on the token row.

Auth is handled via :func:`core.integrations.google_calendar.oauth.
get_valid_access_token`. Each API call refreshes the access token if
the cached one is close to expiry; a persistent 401 (e.g. revoked
upstream) surfaces as :class:`GoogleCalendarTokenExpired` so the
caller can mark the row revoked + skip further calls.

The client is STATELESS — no shared connection pool, no retry loop.
The Celery task in Step 4 owns retry semantics (with exponential
backoff for rate-limit); this layer just maps HTTP status codes to
typed exceptions.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from src.app.core.integrations.google_calendar.exceptions import (
    GoogleCalendarBadResponse,
    GoogleCalendarConcurrencyConflict,
    GoogleCalendarEventGone,
    GoogleCalendarRateLimited,
    GoogleCalendarTokenExpired,
)
from src.app.core.integrations.google_calendar.oauth import (
    GoogleCalendarNotConnected,
    get_valid_access_token,
)


_API_BASE = "https://www.googleapis.com/calendar/v3"
_HTTP_TIMEOUT = 15.0


# --- Event CRUD --------------------------------------------------------


async def create_event(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    calendar_id: str,
    event_body: dict[str, Any],
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """POST an event to the user's calendar. Returns ``(event_id, etag)``.

    Google's response body includes the ``id`` (event id) and the
    response ``ETag`` header. The etag is stored on the appointment
    row so subsequent PATCH calls can use ``If-Match`` for optimistic
    concurrency.
    """
    access_token = await _get_token(
        session, org_id=org_id, user_id=user_id, http_client=http_client
    )
    url = f"{_API_BASE}/calendars/{_url_quote(calendar_id)}/events"
    headers = _auth_headers(access_token)
    response = await _post(url, event_body, headers, http_client)
    _raise_for_status(response, op="create_event")
    body = _safe_json(response) or {}
    event_id = body.get("id")
    etag = body.get("etag") or response.headers.get("etag")
    if not event_id or not etag:
        raise GoogleCalendarBadResponse(
            "create_event: Google response missing id or etag",
            status_code=response.status_code,
        )
    return str(event_id), str(etag)


async def patch_event(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    calendar_id: str,
    event_id: str,
    event_body: dict[str, Any],
    etag: str | None,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """PATCH an existing event. When ``etag`` is supplied it's sent as
    ``If-Match`` — Google returns 412 if the event was edited on
    the Google side since we last read it.

    Returns the new ``(event_id, etag)`` — event_id is unchanged but
    convenient to return alongside so callers have one tuple to
    persist.
    """
    access_token = await _get_token(
        session, org_id=org_id, user_id=user_id, http_client=http_client
    )
    url = (
        f"{_API_BASE}/calendars/{_url_quote(calendar_id)}"
        f"/events/{_url_quote(event_id)}"
    )
    headers = _auth_headers(access_token)
    if etag:
        headers["If-Match"] = etag
    response = await _patch(url, event_body, headers, http_client)
    _raise_for_status(response, op="patch_event", event_id=event_id)
    body = _safe_json(response) or {}
    new_etag = body.get("etag") or response.headers.get("etag")
    if not new_etag:
        raise GoogleCalendarBadResponse(
            f"patch_event: Google response missing etag for {event_id}",
            status_code=response.status_code,
        )
    return event_id, str(new_etag)


async def delete_event(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    calendar_id: str,
    event_id: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """DELETE an event. Idempotent — 404 is treated as success
    (someone deleted it out-of-band, target state matches)."""
    access_token = await _get_token(
        session, org_id=org_id, user_id=user_id, http_client=http_client
    )
    url = (
        f"{_API_BASE}/calendars/{_url_quote(calendar_id)}"
        f"/events/{_url_quote(event_id)}"
    )
    headers = _auth_headers(access_token)
    response = await _delete(url, headers, http_client)
    if response.status_code == 404:
        # Already gone — mission accomplished.
        return
    _raise_for_status(response, op="delete_event", event_id=event_id)


async def get_primary_calendar_id(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """GET the user's primary calendar id. Result is stable across the
    user's account lifetime + should be cached on the token row after
    the first call (see :func:`sync_service.ensure_primary_calendar_id`).
    """
    access_token = await _get_token(
        session, org_id=org_id, user_id=user_id, http_client=http_client
    )
    url = f"{_API_BASE}/users/me/calendarList/primary"
    headers = _auth_headers(access_token)
    response = await _get(url, headers, http_client)
    _raise_for_status(response, op="get_primary_calendar_id")
    body = _safe_json(response) or {}
    cal_id = body.get("id")
    if not cal_id:
        raise GoogleCalendarBadResponse(
            "get_primary_calendar_id: response missing id",
            status_code=response.status_code,
        )
    return str(cal_id)


# --- Internal helpers -------------------------------------------------


async def _get_token(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    http_client: httpx.AsyncClient | None,
) -> str:
    """Wrap :func:`get_valid_access_token` so its
    :class:`GoogleCalendarNotConnected` bubbles up as a typed API
    client error the caller understands.

    We don't try/except broadly here — anything else is a config /
    network issue the caller should see raw."""
    try:
        return await get_valid_access_token(
            session, org_id=org_id, user_id=user_id, http_client=http_client
        )
    except GoogleCalendarNotConnected as exc:
        # Same taxonomy as a 401: the token isn't usable for authorised
        # API calls. The caller marks the row revoked + skips.
        raise GoogleCalendarTokenExpired(str(exc)) from exc


def _auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _url_quote(part: str) -> str:
    """URL-quote a calendar or event id. Calendar ids are usually
    email addresses (``ajay@gmail.com``) — the ``@`` must be encoded
    to ``%40`` for the path. Event ids are Google-generated + safe but
    quote for defence in depth."""
    from urllib.parse import quote

    return quote(part, safe="")


async def _get(
    url: str,
    headers: dict[str, str],
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    if http_client is not None:
        return await http_client.get(url, headers=headers)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        return await client.get(url, headers=headers)


async def _post(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    if http_client is not None:
        return await http_client.post(url, json=body, headers=headers)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        return await client.post(url, json=body, headers=headers)


async def _patch(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    if http_client is not None:
        return await http_client.patch(url, json=body, headers=headers)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        return await client.patch(url, json=body, headers=headers)


async def _delete(
    url: str,
    headers: dict[str, str],
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    if http_client is not None:
        return await http_client.delete(url, headers=headers)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        return await client.delete(url, headers=headers)


def _safe_json(response: httpx.Response) -> dict | None:
    try:
        return response.json()
    except ValueError:
        return None


def _raise_for_status(
    response: httpx.Response,
    *,
    op: str,
    event_id: str | None = None,
) -> None:
    """Map Google's HTTP status → typed exception. Success (2xx) is a
    no-op. Called by every operation right after the request."""
    status = response.status_code
    if 200 <= status < 300:
        return

    body = _safe_json(response) or {}
    error_block = body.get("error") or {}
    reason = _first_error_reason(error_block)
    message = error_block.get("message") or response.text[:200]

    if status == 401:
        raise GoogleCalendarTokenExpired(
            f"{op}: Google returned 401 — {message}"
        )
    if status == 403 and reason in (
        "userRateLimitExceeded",
        "rateLimitExceeded",
        "quotaExceeded",
    ):
        raise GoogleCalendarRateLimited(
            f"{op}: Google rate-limited ({reason}) — {message}"
        )
    if status == 404:
        raise GoogleCalendarEventGone(
            f"{op}: Google returned 404 for event={event_id} — {message}"
        )
    if status == 412:
        raise GoogleCalendarConcurrencyConflict(
            f"{op}: If-Match mismatch (event was edited in Google) — {message}"
        )
    raise GoogleCalendarBadResponse(
        f"{op}: Google returned {status} — {message}",
        status_code=status,
    )


def _first_error_reason(error_block: dict[str, Any]) -> str | None:
    """Pull the first ``errors[0].reason`` out of Google's error
    envelope. Returns ``None`` when the envelope is missing / empty."""
    errors = error_block.get("errors") or []
    if not errors or not isinstance(errors, list):
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    reason = first.get("reason")
    return str(reason) if reason else None


__all__ = [
    "create_event",
    "delete_event",
    "get_primary_calendar_id",
    "patch_event",
]
