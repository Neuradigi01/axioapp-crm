"""Public webhook receiver + Celery task for Mailgun delivery events.

Endpoint: ``POST /api/v1/webhooks/mailgun/events``

Payload contract (Mailgun v3 events webhook — JSON body):

    {
      "signature": {
        "timestamp": "1529006854",
        "token":     "a8ce0edb2dd8301dee6c2405235584e45aa91d1e9f979f3de0",
        "signature": "d2271d12299f6592d9d44cd9d250f0704e4674c30d79d07c47a66f95ce71cf1e"
      },
      "event-data": {
        "id":        "CPgfbmQMTCKtHW6uIWtuVe",
        "event":     "delivered" | "failed" | "complained" | "unsubscribed" | ...,
        "severity":  "permanent" | "temporary"   (only when event=failed),
        "timestamp": 1529006854.329327,
        "user-variables": {                     ← Mailgun strips the ``v:`` prefix
          "org":      "<uuid>",
          "envelope": "platform_from" | "own_domain",
          "domain_id":"<uuid or omitted>",
          "endpoint": "<uuid or omitted>",
          "campaign": "<uuid or omitted>"
        },
        ...
      }
    }

Signature is verified via the same HMAC helper the inbound webhook
uses (``service.verify_signature``) — same signing key, same 5-min
window. On sig failure the endpoint returns **406** (Mailgun's
retry docs treat 406 as a structural reject — no retry) so a
misconfigured signing key doesn't bury our webhook under Mailgun's
8-hour retry ladder. Rate-limit on sig failure is 20/min/IP,
matching the inbound webhook.

Event dedup uses the ``event-data.id`` field with a 10-min Redis
TTL (Mailgun retries a failed webhook for 8h with 5m→…→4h backoff;
a 10-min window catches every retry that could reach us during a
brief broker outage). Fail-CLOSED — Redis down means we 5xx, and
Mailgun retries.

Persist-then-process: the raw JSON body lands under
``./storage/pending-events/<uuid>/payload.json`` BEFORE we .delay()
the Celery task, so a broker outage after our 200 doesn't lose
the event. A future sweeper (Step 4/beat) can re-enqueue pending-
events directories the same way the inbound sweeper does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from src.app.core import audit
from src.app.core.email.mailgun import data_access as mailgun_da
from src.app.core.email.mailgun import service as mailgun_service
from src.app.core.email.reputation import service as reputation_service
from src.app.shared.db import async_session
from src.app.shared.rate_limit_shared import _redis, rate_hit  # type: ignore[attr-defined]
from src.app.shared.storage import storage_root
from src.celery.worker import celery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mailgun", tags=["Mailgun Events"])

# ``mgw:events:seen:{event_id}`` — dedup Mailgun's own retries.
# Separate namespace from ``mgw:seen:`` (signature-triplet replay)
# so ops can grep + expire the two independently.
_EVENT_DEDUP_PREFIX = "mgw:events:seen:"
_EVENT_DEDUP_TTL_SECONDS = 600  # 10 minutes (spec §Step 3)

_FAIL_RATE_KEY_PREFIX = "mgw:events:fail:"
_FAIL_RATE_LIMIT = 20
_FAIL_RATE_WINDOW_SECONDS = 60

# Storage layout mirrors the inbound webhook's ``pending-inbound/`` but
# in a separate subdir — event payloads have a different schema and
# get processed by a different task; the two must not collide.
_PENDING_SUBDIR = "pending-events"


async def _check_and_record_event_id(event_id: str) -> bool:
    """Redis SET NX PX for the ``event-data.id`` field. Returns
    True when the event is fresh (proceed) and False on either a
    genuine Mailgun retry replay OR a Redis outage (fail-CLOSED —
    a duplicate persist is worse than a 5xx that Mailgun retries).
    """
    if not event_id:
        return False
    client = _redis()
    if client is None:
        logger.error("mailgun.events.dedup: redis client unavailable — failing closed")
        return False
    try:
        result = await client.set(
            f"{_EVENT_DEDUP_PREFIX}{event_id}",
            "1",
            nx=True,
            px=_EVENT_DEDUP_TTL_SECONDS * 1000,
        )
        return bool(result)
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("mailgun.events.dedup: redis error — %s — failing closed", exc)
        return False


async def _persist_event_payload(body: dict[str, Any]) -> Path:
    """Write the raw JSON body under ``./storage/pending-events/
    {uuid}/payload.json`` so the webhook can return 200 BEFORE the
    broker enqueue. Returns the created directory (also the enqueue
    argument)."""
    request_id = uuid.uuid4()
    pending_dir = storage_root() / _PENDING_SUBDIR / str(request_id)
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "payload.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8"
    )
    return pending_dir


def _enqueue_process_task(pending_path: Path) -> bool:
    """Dispatch the ingest Celery task. Return True on success, False
    when the broker refused — the webhook still returns 200; a
    future sweeper picks up the on-disk directory.
    """
    try:
        process_mailgun_event.delay(str(pending_path))
        return True
    except Exception as exc:  # pragma: no cover — broker outage path
        logger.warning(
            "mailgun.events.enqueue failed for %s: %s — sweeper will pick up",
            pending_path,
            exc,
        )
        return False


@router.post("/events", include_in_schema=False)
async def mailgun_events(request: Request) -> JSONResponse:
    """Receive one Mailgun delivery event.

    Flow: read JSON body → verify HMAC signature → dedup by
    ``event-data.id`` → persist raw payload → enqueue Celery task →
    return 200. Same "constant-time to Mailgun regardless of
    downstream state" discipline the inbound webhook uses.
    """
    client_ip = request.client.host if request.client else None
    try:
        body = await request.json()
    except Exception:
        # Malformed JSON — treat like a bad signature. Mailgun's own
        # payload is always well-formed JSON, so this shape is an
        # attacker probe or a middleware bug on our side.
        if client_ip:
            await rate_hit(
                f"{_FAIL_RATE_KEY_PREFIX}{client_ip}",
                _FAIL_RATE_LIMIT,
                _FAIL_RATE_WINDOW_SECONDS,
            )
        await audit.log(
            "mailgun.events.malformed_body",
            entity_type="webhook_attempt",
            after={"reason": "json_parse_error"},
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content={"error": "malformed body"},
        )

    sig = body.get("signature") or {}
    timestamp = str(sig.get("timestamp", ""))
    token = str(sig.get("token", ""))
    signature = str(sig.get("signature", ""))

    if not mailgun_service.verify_signature(timestamp=timestamp, token=token, signature=signature):
        if client_ip:
            await rate_hit(
                f"{_FAIL_RATE_KEY_PREFIX}{client_ip}",
                _FAIL_RATE_LIMIT,
                _FAIL_RATE_WINDOW_SECONDS,
            )
        await audit.log(
            "mailgun.events.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "reason": "bad_signature",
                "timestamp_present": bool(timestamp),
                "token_present": bool(token),
                "signature_present": bool(signature),
            },
            org_id=None,
            ip=client_ip,
        )
        # 406 = Mailgun's "structural reject; do not retry" per docs.
        # Better than 401 here — we don't want an 8h retry loop when
        # the signing key is misconfigured (the endpoint won't fix
        # itself in that window).
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content={"error": "bad signature"},
        )

    # Signature-triplet replay (attacker capture + replay of the exact
    # HMAC triplet) shares the inbound webhook's ``mgw:seen:`` cache.
    # A hostile actor with a captured triplet from the inbound webhook
    # can't reuse it against events (different endpoint) and vice
    # versa — but both paths guard the same window.
    fresh_triplet = await mailgun_da.check_and_record_replay(token)
    if not fresh_triplet:
        await audit.log(
            "mailgun.events.replay_triplet_rejected",
            entity_type="webhook_attempt",
            after={"reason": "replay_or_redis_outage"},
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content={"error": "replay"},
        )

    event_data = body.get("event-data") or {}
    event_id = str(event_data.get("id", "") or "")
    if not event_id:
        # No id → we can't dedup future Mailgun retries. Structural
        # reject — a legitimate Mailgun payload always includes the
        # event id.
        await audit.log(
            "mailgun.events.missing_event_id",
            entity_type="webhook_attempt",
            after={"reason": "no_event_data_id"},
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content={"error": "missing event id"},
        )

    fresh_event = await _check_and_record_event_id(event_id)
    if not fresh_event:
        # Genuine Mailgun retry OR Redis outage — either way, return
        # 200 so Mailgun stops retrying (retry-storm mitigation). The
        # counter effect was applied on the first receipt.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "duplicate"},
        )

    # Persist BEFORE enqueue so a broker outage doesn't lose the event.
    try:
        pending_dir = await _persist_event_payload(body)
    except Exception:  # pragma: no cover — disk-full / permissions
        logger.exception("mailgun.events: failed to persist pending event")
        await audit.log(
            "mailgun.events.persist_failed",
            entity_type="webhook_attempt",
            after={"reason": "disk_write_error"},
            org_id=None,
            ip=client_ip,
        )
        # 500 → Mailgun retries. Better than silently dropping.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "persist failed"},
        )

    _enqueue_process_task(pending_dir)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "accepted"},
    )


# ---------------------------------------------------------------------------
# Celery task — invoked by the webhook after persist.
# ---------------------------------------------------------------------------


@celery.task(
    name="src.app.core.email.mailgun.events_webhook.process_mailgun_event",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def process_mailgun_event(self, pending_path: str) -> None:
    """Ingest one persisted Mailgun event payload.

    Reads ``payload.json``, extracts the attribution ``v:`` variables
    (Mailgun's ``event-data.user-variables`` sub-object), and calls
    :func:`reputation_service.handle_mailgun_event` which owns the
    counter bump + row upsert. Cleans up the pending dir on success.

    Missing ``v:org`` audits ``mailgun.event.missing_v_org`` + drops —
    an event we can't attribute to a tenant is meaningless (and
    counting it against a synthetic "unknown" bucket would hide
    outbound bugs).
    """
    try:
        asyncio.run(_process_event_async(Path(pending_path)))
    except Exception:
        if self.request.retries >= (self.max_retries or 0):
            logger.error(
                "mailgun.events: retries exhausted for %s — dropping "
                "(counter drift +0 for this event)",
                pending_path,
            )
            _cleanup(Path(pending_path))
            return
        raise


async def _process_event_async(pending_dir: Path) -> None:
    if not pending_dir.exists():
        logger.info(
            "mailgun.events: pending path %s missing — likely already processed",
            pending_dir,
        )
        return

    payload_file = pending_dir / "payload.json"
    if not payload_file.exists():
        logger.warning(
            "mailgun.events: payload.json missing under %s — cleaning up",
            pending_dir,
        )
        _cleanup(pending_dir)
        return

    try:
        body: dict[str, Any] = json.loads(payload_file.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("mailgun.events: payload.json parse failed at %s", pending_dir)
        _cleanup(pending_dir)
        return

    event_data = body.get("event-data") or {}
    user_vars = event_data.get("user-variables") or {}
    event_kind = str(event_data.get("event") or "").strip().lower()
    severity_raw = event_data.get("severity")
    severity = str(severity_raw).strip().lower() if severity_raw else None

    org_raw = user_vars.get("org")
    envelope_raw = user_vars.get("envelope")
    domain_raw = user_vars.get("domain_id")

    if not org_raw or not envelope_raw:
        await audit.log(
            "mailgun.event.missing_v_org",
            entity_type="webhook_attempt",
            after={
                "reason": "missing_org_or_envelope",
                "event": event_kind,
                "event_id": event_data.get("id"),
                "org_present": bool(org_raw),
                "envelope_present": bool(envelope_raw),
            },
            org_id=None,
        )
        _cleanup(pending_dir)
        return

    try:
        org_id = uuid.UUID(str(org_raw))
    except ValueError:
        await audit.log(
            "mailgun.event.malformed_v_org",
            entity_type="webhook_attempt",
            after={"reason": "org_not_uuid", "value": str(org_raw)[:64]},
            org_id=None,
        )
        _cleanup(pending_dir)
        return

    envelope_type = str(envelope_raw).strip()
    if envelope_type not in ("platform_from", "own_domain"):
        await audit.log(
            "mailgun.event.malformed_v_envelope",
            entity_type="webhook_attempt",
            after={"reason": "envelope_not_enum", "value": envelope_type[:32]},
            org_id=None,
        )
        _cleanup(pending_dir)
        return

    domain_id: uuid.UUID | None = None
    if envelope_type == "own_domain":
        if not domain_raw:
            await audit.log(
                "mailgun.event.missing_v_domain_id",
                entity_type="webhook_attempt",
                after={"reason": "own_domain_without_domain_id"},
                org_id=org_id,
            )
            _cleanup(pending_dir)
            return
        try:
            domain_id = uuid.UUID(str(domain_raw))
        except ValueError:
            await audit.log(
                "mailgun.event.malformed_v_domain_id",
                entity_type="webhook_attempt",
                after={"reason": "domain_id_not_uuid", "value": str(domain_raw)[:64]},
                org_id=org_id,
            )
            _cleanup(pending_dir)
            return

    async with async_session() as session:
        # RLS scope for the worker — mirrors the inbound task pattern.
        from sqlalchemy import text as sql_text

        await session.execute(
            sql_text("SELECT set_config('app.current_org_id', :o, TRUE)"),
            {"o": str(org_id)},
        )
        await reputation_service.handle_mailgun_event(
            session,
            org_id=org_id,
            envelope_type=envelope_type,
            domain_id=domain_id,
            event_kind=event_kind,
            severity=severity,
        )

    _cleanup(pending_dir)


def _cleanup(pending_dir: Path) -> None:
    """Remove the on-disk pending-events directory after a
    successful (or intentionally-dropped) event."""
    try:
        shutil.rmtree(pending_dir)
    except FileNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover — filesystem edge
        logger.warning(
            "mailgun.events: failed to remove pending dir %s: %s",
            pending_dir,
            exc,
        )


__all__ = ["process_mailgun_event", "router"]
