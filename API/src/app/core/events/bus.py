"""Process-local pub/sub primitives for CRM domain events.

The bus is one module-level dict — ``event_type → list[handler]``.
Subscribers register at module-import time during the FastAPI
lifespan startup (the conversations adapters use the same pattern).
The publisher awaits each registered handler in turn; failures are
logged + swallowed so one bad subscriber doesn't poison the rest.

Step 1 of ``tasks/automation-engine/`` lands the primitives. No
domain events publish yet; no automation handlers are subscribed
yet. Step 4 wires the automation dispatcher as a subscriber; Steps
5 / 6 / 10 / 11 / 12 wire the actual publish() calls from the
origin modules (``user.signed_up`` from auth, ``lead.created``
from every lead-capture source, etc.).

Multi-worker note: the bus is process-local — each uvicorn worker +
each Celery worker has its own dict. For v1 the actual handler
work that needs cross-process consistency runs through the Celery
task queue (the dispatcher Step 4 ships); the bus only routes from
"publish call" to "queue a Celery job". When a future step needs
true cross-worker fan-out (e.g. WebSocket push from any worker),
swap this module's dict for a Redis-backed pub/sub without changing
the call surface.

Event-type taxonomy (string constants — modules importing this
should pull from this list, not hardcode):

Auth + onboarding
    ``user.signed_up`` — a fresh Owner finishes registration
    ``user.invited`` — operator invites a new team member
    ``user.invitation_accepted`` — invited user finishes signup
    ``user.first_login`` — first successful login after signup
    ``user.role_changed`` — membership role changes (Owner-only)

Leads + contacts
    ``lead.created`` — fired by EVERY lead-capture source
                       (form widget, Google/Meta Ads webhook, CSV
                       import, manual entry, walk-in, WhatsApp
                       inbound new-contact, API direct)
    ``lead.status_changed`` — status transition
    ``lead.score_threshold`` — score crosses a configured threshold
    ``lead.assigned`` — owner assignment changes
    ``lead.converted`` — lead → contact promotion
    ``lead.stale_7d`` / ``lead.stale_30d`` / ``lead.stale_90d``
    ``contact.created``
    ``contact.birthday`` — daily sweep finds a contact's birthday
    ``contact.anniversary``
    ``contact.opt_in_changed``

Appointments + walk-ins
    ``appointment.booked``
    ``appointment.reminder_24h`` / ``appointment.reminder_1h``
    ``appointment.completed`` / ``appointment.missed``
    ``walk_in.registered``

Sales
    ``quote.sent`` / ``quote.viewed`` / ``quote.accepted`` /
    ``quote.rejected`` / ``quote.expired``
    ``invoice.sent`` / ``invoice.paid``
    ``invoice.overdue_7d`` / ``invoice.overdue_14d`` /
    ``invoice.overdue_30d``

Communications
    ``email.opened`` / ``email.clicked`` / ``email.replied``
    ``whatsapp.message_received`` / ``whatsapp.template_replied``

Time-based (emitted by the daily sweep)
    ``time.daily_tick`` — once a day at org-local midnight
"""
from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any, Awaitable, Callable, Union


logger = logging.getLogger(__name__)


#: Handler signature — coroutine fn called with the published
#: payload (already enriched with ``org_id``). Sync callables are
#: also accepted to keep test fixtures simple; their return value
#: is discarded.
EventHandler = Callable[[dict[str, Any]], Union[None, Awaitable[None]]]


# Process-local registry. Keyed by exact event-type string match;
# wildcard patterns are NOT supported (would invite surprise fan-out).
_subscribers: dict[str, list[EventHandler]] = {}


def subscribe(event_type: str, handler: EventHandler) -> None:
    """Register ``handler`` to receive every ``publish(event_type, …)``
    fire-and-forget event going forward. Safe to call before any
    publishers exist — the handler simply never fires until something
    publishes.

    Registration is idempotent on ``(event_type, handler)`` — calling
    twice doesn't double-fire the handler."""
    bucket = _subscribers.setdefault(event_type, [])
    if handler in bucket:
        return
    bucket.append(handler)


def unsubscribe(event_type: str, handler: EventHandler) -> None:
    """Remove a handler. Mostly a test helper — production
    subscribers register at app-start + stay registered for the
    process lifetime."""
    bucket = _subscribers.get(event_type)
    if not bucket:
        return
    try:
        bucket.remove(handler)
    except ValueError:
        return


async def publish(
    event_type: str,
    payload: dict[str, Any],
    *,
    org_id: uuid.UUID,
) -> None:
    """Fire ``event_type`` with ``payload`` to every registered
    handler. The published envelope is the caller's payload merged
    with ``{"org_id": org_id, "event_type": event_type}`` so
    handlers always see who fired what.

    Each handler is awaited in turn. A handler raising is logged and
    swallowed so one bad subscriber doesn't block the next one (and
    so the publisher's transaction completes regardless).

    No handlers registered → no-op + a debug log line. Origin
    modules can publish forward-compatible event types before the
    consumer module subscribes.
    """
    envelope: dict[str, Any] = {
        **payload,
        "org_id": org_id,
        "event_type": event_type,
    }
    handlers = list(_subscribers.get(event_type, ()))
    if not handlers:
        logger.debug(
            "events.publish no_subscribers event_type=%s org_id=%s",
            event_type,
            org_id,
        )
        return
    for handler in handlers:
        try:
            result = handler(envelope)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "events.handler_failed event_type=%s handler=%s",
                event_type,
                getattr(handler, "__qualname__", repr(handler)),
            )


def _clear_subscribers_for_tests() -> None:
    """Test helper — wipes the registry between cases so subscribers
    from one test don't bleed into the next. NOT exported via
    ``__all__``; intentionally underscore-prefixed."""
    _subscribers.clear()


__all__ = ["EventHandler", "publish", "subscribe", "unsubscribe"]
