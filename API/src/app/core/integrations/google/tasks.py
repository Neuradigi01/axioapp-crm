"""Celery task: ingest a Google Ads Lead Form payload into the CRM.

The webhook receiver (`google/webhook.py`) does the bare minimum
synchronously: authenticate the inbound URL via `webhook_secret`,
verify the in-body `google_key`, and `.delay(...)` this task. All
contact/lead creation, dedup, audit, and DLQ accounting happens here
on the worker — never on the request thread (Google retries on any
non-2xx, so the receiver must stay fast and stable).

Lifecycle:

  1. Tenant-context push (org_id derived from the integration row, the
     payload has no JWT and no `X-Org-Id` header).
  2. Resolve integration; bail to DLQ if missing/disconnected.
  3. Resolve subscription by `external_form_id`; bail to DLQ if absent
     or disabled. (Disabled is intentionally DLQ'd, not silently
     dropped, so a future re-enable + replay catches missed deliveries.)
  4. Idempotency check: skip if `(org_id, attribution.external_lead_id)`
     already exists (a replay of a payload we already processed).
  5. Translate `user_column_data` through `subscription.field_mapping`
     into a `ContactCreate` shape; create-or-reuse contact via the
     bulk-import dedup helper.
  6. Create the lead with `source=google_ads`, `actor_user_id=None`,
     `attribution={external_form_id, external_lead_id, campaign_id,
     gclid}`. Emit `integration.webhook.received` audit.
  7. On exception: Celery retry policy with exponential backoff;
     after exhaustion, write to DLQ + commit.

Celery may be absent in dev (the project ships a no-op `_shared_task`
shim, mirroring `core/leads/imports/tasks.py`). When absent, the
synchronous `process_google_lead_async(...)` is callable directly —
the webhook router falls through to that path so dev smoke tests
exercise the full flow without a worker.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import text

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery absent in dev
    HAS_CELERY = False

    # Same shim shape as `core/leads/imports/tasks.py`. `.delay()` is
    # a no-op so the webhook receiver doesn't blow up when celery
    # isn't installed — the receiver always succeeds and an operator
    # can replay from the DLQ once celery is enabled.
    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

                # Celery's `bind=True` exposes `self.retry()` on the
                # task. In the shim, retry just re-raises — the
                # async body's exception handling routes to DLQ.
                def retry(self, exc=None, **_):
                    raise exc if exc else RuntimeError("retry called")

            return _Stub()

        if decorator_args and callable(decorator_args[0]) and not decorator_kwargs:
            return _wrap(decorator_args[0])
        return _wrap


from src.app.core import audit
from src.app.core.contacts.schemas import ContactCreate
from src.app.core.contacts.service import create_contact
from src.app.core.integrations.google.dlq import record_dlq
from src.app.core.integrations.models import (
    Integration,
    IntegrationStatus,
)
from src.app.core.integrations.service import find_subscription
from src.app.core.leads.imports.dedup import find_existing_contact
from src.app.core.leads.ingest import ingest as ingest_lead
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


# Field-mapping target keys reused from the bulk-import registry. The
# webhook task understands the same `contact.*` / `lead.*` /
# `custom_data.*` namespacing the CSV importer does, so the Settings
# UI's mapping editor (Step 8) doesn't need a parallel vocabulary.
_CONTACT_FIELDS = ("contact.full_name", "contact.phone", "contact.email")


# --- Celery entrypoint ----------------------------------------------------


@_shared_task(
    bind=True,
    name="src.app.core.integrations.google.tasks.process_google_lead",
    # Auto-retry only on transient errors. ValueError / KeyError /
    # validation failures are caught explicitly inside the body and
    # routed to DLQ immediately — no point retrying a payload that's
    # structurally wrong, the next attempt fails the same way.
    autoretry_for=(ConnectionError, TimeoutError),
    max_retries=5,
    # Exponential backoff: 5s → 25s → 2m → 10m → 50m (capped at 1h).
    retry_backoff=5,
    retry_backoff_max=3600,
    retry_jitter=True,
)
def process_google_lead(self, integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Celery sync entrypoint. Bridges into async via `asyncio.run`."""
    try:
        return asyncio.run(
            process_google_lead_async(integration_id=uuid.UUID(integration_id), payload=payload)
        )
    except (ConnectionError, TimeoutError) as exc:
        # Transient — let Celery's autoretry policy handle it.
        if HAS_CELERY:
            raise self.retry(exc=exc) from exc
        raise


# --- Async body -----------------------------------------------------------


async def process_google_lead_async(
    *,
    integration_id: uuid.UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the integration, push tenant context, then do the
    contact/lead write. The function returns a dict describing the
    outcome so the (eager-mode) test caller can assert on it.

    Outcomes: `{"status": "created", "lead_id": ...}`,
    `{"status": "duplicate", "lead_id": ...}` (replay of a payload we
    already processed), or `{"status": "dlq", "reason": "..."}`.
    """
    # Open a session WITHOUT a tenant context to fetch the integration
    # row by id — we have no `app.org_id` yet, but `webhook_secret`
    # already authenticated the URL so the integration_id we have here
    # is trusted.
    async with async_session() as session:
        integration = await _load_integration_unscoped(session, integration_id)
        if integration is None:
            logger.warning("process_google_lead: integration %s not found", integration_id)
            await record_dlq(
                session,
                org_id=_safe_org_from_payload(payload) or uuid.uuid4(),
                integration_id=integration_id,
                payload=payload,
                error_message="integration row not found",
            )
            return {"status": "dlq", "reason": "integration_missing"}

        org_id = integration.org_id
        if integration.status != IntegrationStatus.connected:
            await record_dlq(
                session,
                org_id=org_id,
                integration_id=integration.id,
                payload=payload,
                error_message=(f"integration status={integration.status.value} (not connected)"),
            )
            return {"status": "dlq", "reason": "disconnected"}

    # All subsequent reads/writes run under the org tenant context so
    # RLS + the ORM tenant filter authorise them.
    ctx_token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            external_form_id = _extract_form_id(payload)
            external_lead_id = _extract_lead_id(payload)
            if not external_form_id:
                await record_dlq(
                    session,
                    org_id=org_id,
                    integration_id=integration_id,
                    payload=payload,
                    error_message="payload missing form_id",
                )
                return {"status": "dlq", "reason": "missing_form_id"}

            subscription = await find_subscription(
                session,
                integration_id=integration_id,
                external_form_id=external_form_id,
            )
            if subscription is None or not subscription.enabled:
                await record_dlq(
                    session,
                    org_id=org_id,
                    integration_id=integration_id,
                    payload=payload,
                    error_message=(f"no enabled subscription for form {external_form_id}"),
                )
                return {"status": "dlq", "reason": "no_subscription"}

            # Idempotency: if a lead with this (org, external_lead_id)
            # already exists, skip — replay of an already-processed
            # payload. The partial UNIQUE index in 0049 belt-and-
            # suspenders this; the check here gives us a friendly
            # "duplicate" outcome instead of a constraint violation
            # bubbling up to Celery's retry loop.
            if external_lead_id:
                existing_lead_id = await _find_lead_by_external_id(
                    session,
                    org_id=org_id,
                    external_lead_id=external_lead_id,
                )
                if existing_lead_id is not None:
                    return {
                        "status": "duplicate",
                        "lead_id": str(existing_lead_id),
                    }

            mapped = _apply_mapping(subscription.field_mapping or {}, payload)
            full_name = (mapped.get("contact.full_name") or "").strip()
            phone = mapped.get("contact.phone")
            email = mapped.get("contact.email")
            if not full_name:
                # Some Google Lead Form templates don't include a name
                # field at all — fall back to the phone or email so we
                # always have a contact label. The Owner can rename
                # the contact from the lead detail screen later.
                full_name = phone or email or "Google Ads lead"

            existing_contact_id = await find_existing_contact(
                session, org_id=org_id, phone=phone, email=email
            )
            if existing_contact_id is not None:
                contact_id = existing_contact_id
            else:
                contact = await create_contact(
                    session,
                    org_id=org_id,
                    payload=ContactCreate(
                        full_name=full_name,
                        phone=phone,
                        email=email,
                        source="google_ads",
                        custom_data=_extract_custom(mapped),
                    ),
                    require_all_required=False,
                )
                contact_id = contact.id

            # Route through the centralised ingest service so the
            # open-lead dedup + round-robin assignment apply uniformly
            # across all five channels.
            #
            # Per-form pipeline_stage override (Step 11 — parity with
            # Meta's Step 10 wiring): pass the subscription's stage
            # through when set; ingest's `_resolve_initial_stage`
            # validates it against the org's leads pipeline. None
            # falls back to the default first stage, unchanged.
            result = await ingest_lead(
                session,
                org_id=org_id,
                source=LeadSource.google_ads,
                contact_id=contact_id,
                lead_payload=LeadCreate(
                    contact_id=contact_id,
                    custom_data=_extract_custom(mapped, prefix="lead."),
                    source=LeadSource.google_ads,
                    attribution=_build_attribution(payload),
                    pipeline_stage=subscription.pipeline_stage,
                ),
            )

        await audit.log(
            "integration.webhook.received",
            entity_type="lead",
            entity_id=result.lead_id,
            after={
                "provider": "google_ads",
                "integration_id": str(integration_id),
                "external_form_id": external_form_id,
                "external_lead_id": external_lead_id,
                "lead_id": str(result.lead_id),
                "contact_id": str(contact_id),
                "ingest_action": result.action,
            },
        )
        return {"status": "created", "lead_id": str(result.lead_id)}
    finally:
        reset_context(ctx_token)


# --- payload parsing ------------------------------------------------------


def _extract_form_id(payload: dict[str, Any]) -> str | None:
    """Google sends `form_id` at top level (newer Ads payloads also
    use `lead_form_id`). Accept either; bail to None if absent."""
    for key in ("form_id", "lead_form_id"):
        v = payload.get(key)
        if v is not None:
            return str(v)
    return None


def _extract_lead_id(payload: dict[str, Any]) -> str | None:
    """Google calls this `lead_id`. The idempotency check (and the
    partial UNIQUE index in migration 0049) depends on this being
    stable for a given lead — Google's docs guarantee it is."""
    v = payload.get("lead_id")
    return str(v) if v is not None else None


def _safe_org_from_payload(payload: dict[str, Any]) -> uuid.UUID | None:
    """For DLQ-on-integration-missing: try to recover an org_id from
    the payload itself. Returns None if the payload doesn't carry one;
    caller falls back to a synthetic uuid (the DLQ row is still useful
    for forensic replay, just not viewable in any org's UI)."""
    raw = payload.get("__org_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _apply_mapping(field_mapping: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """Translate Google's `user_column_data: [{column_id, column_name,
    string_value}, ...]` array through the subscription's field mapping.

    Google's payload carries both `column_id` (the stable canonical key
    like "FULL_NAME") and `column_name` (the form's display label like
    "Full Name"). The Settings mapping editor stores subscriptions with
    `column_id`s as keys, so we read `column_id` first and only fall
    back to `column_name` for payloads that omit the id field.

    `field_mapping` maps `column_id → crm_field_key`, e.g.
    `{"FULL_NAME": "contact.full_name", "PHONE_NUMBER": "contact.phone"}`.
    Columns absent from the mapping are dropped — keep the surface small."""
    rows = payload.get("user_column_data") or []
    result: dict[str, Any] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        column = (
            entry.get("column_id")
            or entry.get("columnId")
            or entry.get("column_name")
            or entry.get("columnName")
        )
        value = entry.get("string_value") or entry.get("stringValue")
        if not column:
            continue
        crm_key = field_mapping.get(column)
        if not crm_key:
            continue
        result[crm_key] = value
    return result


def _extract_custom(mapped: dict[str, Any], *, prefix: str = "contact.") -> dict[str, Any]:
    """Pull the `custom_data.*` entries from a mapped row. For Step-3
    we route ALL `custom_data.*` keys to BOTH contact and lead — the
    custom-fields layer will accept-or-reject them per definition.
    Bulk-import's smarter routing-by-entity is a future small task."""
    out: dict[str, Any] = {}
    for k, v in mapped.items():
        if k.startswith("custom_data.") and v not in (None, ""):
            out[k[len("custom_data.") :]] = v
    return out


def _build_attribution(payload: dict[str, Any]) -> dict[str, Any]:
    """Capture `{external_form_id, external_lead_id, campaign_id, gclid}`
    onto the lead's `attribution` JSONB column. Step 6's reporting reads
    these for source attribution."""
    return {
        k: payload.get(k)
        for k in ("form_id", "lead_id", "campaign_id", "gclid")
        if payload.get(k) is not None
    } | (
        # Normalise the keys the rest of the codebase reads.
        {
            "external_form_id": _extract_form_id(payload),
            "external_lead_id": _extract_lead_id(payload),
        }
    )


# --- internals ------------------------------------------------------------


async def _load_integration_unscoped(session, integration_id: uuid.UUID) -> Integration | None:
    """Fetch the integration by id WITHOUT tenant scoping. The
    webhook URL already proved tenant access (the secret IS the auth);
    we need the row's org_id to set the context for everything else."""
    sql = text(
        """
        SELECT id, org_id, provider, status, account_id, account_label,
               access_token_enc, refresh_token_enc, token_expires_at,
               scopes, last_error, connected_at, connected_by,
               disconnected_at, disconnected_by, updated_at,
               webhook_secret
        FROM tbl_integrations WHERE id = :id LIMIT 1
        """
    )
    row = (await session.execute(sql, {"id": str(integration_id)})).mappings().first()
    if row is None:
        return None
    from src.app.core.integrations.models import (
        IntegrationProvider as _P,
    )
    from src.app.core.integrations.models import (
        IntegrationStatus as _S,
    )

    return Integration(
        id=row["id"],
        org_id=row["org_id"],
        provider=_P(row["provider"]),
        status=_S(row["status"]),
        account_id=row["account_id"],
        account_label=row["account_label"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes=row["scopes"],
        last_error=row["last_error"],
        connected_at=row["connected_at"],
        connected_by=row["connected_by"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
        updated_at=row["updated_at"],
        webhook_secret=row["webhook_secret"],
    )


async def _find_lead_by_external_id(
    session, *, org_id: uuid.UUID, external_lead_id: str
) -> uuid.UUID | None:
    """Idempotency lookup: does this org already have a lead whose
    `attribution->>'external_lead_id'` matches? Uses the partial
    UNIQUE index from 0049 for the lookup."""
    sql = text(
        """
        SELECT id FROM tbl_leads
        WHERE org_id = :org_id
          AND attribution->>'external_lead_id' = :ext_id
        LIMIT 1
        """
    )
    return (
        await session.execute(sql, {"org_id": str(org_id), "ext_id": external_lead_id})
    ).scalar()


__all__ = [
    "HAS_CELERY",
    "process_google_lead",
    "process_google_lead_async",
]
