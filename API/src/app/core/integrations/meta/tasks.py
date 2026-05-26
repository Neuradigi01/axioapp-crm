"""Celery task: fetch + ingest a Meta Lead Ads lead.

Meta's `leadgen` webhook payload carries only the lead's `leadgen_id`
— not the field values. The worker has to call
`GET https://graph.facebook.com/v19.0/{leadgen_id}?fields=field_data,...`
with the matching Page-scoped token to get the actual answers the
visitor submitted, then translate them through the subscription's
field mapping into a `ContactCreate` + `LeadCreate`.

Lifecycle:

  1. Look up the (org_id, integration_id, page_token) tuple by
     `page_id` from the cached `meta_page_tokens` table (populated
     during `subscribe_page`). Missing → DLQ + abort. (Webhook
     receiver has already authenticated the delivery via HMAC; the
     only reason a `page_id` would be unknown here is a race between
     a Page being subscribed-then-unsubscribed and Meta's still-in-
     flight delivery, which is rare but worth surfacing in DLQ.)
  2. Push the org's tenant context so RLS authorises every
     subsequent read/write.
  3. Find the `integration_subscriptions` row by `external_form_id`.
     None or disabled → DLQ.
  4. Idempotency: skip if `(org_id, attribution.external_lead_id)`
     already exists. The partial UNIQUE index from migration 0049
     enforces this at the DB level too.
  5. Fetch `/{leadgen_id}` with the Page token. Translate
     `field_data: [{name, values:[v]}, ...]` to the CRM shape via
     the subscription's field mapping.
  6. Find-or-create contact (Step 6's dedup), create lead with
     `source=meta_ads` + attribution `{external_form_id,
     external_lead_id, page_id, ad_id, campaign_id}`.
  7. Emit `integration.webhook.received` audit.

Retry policy: same as the Google task — autoretry on
`(ConnectionError, TimeoutError)` only; structural errors DLQ
immediately. Exponential backoff capped at 1 hour, 5 retries.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

import httpx
from sqlalchemy import text

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery absent in dev
    HAS_CELERY = False

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

                def retry(self, exc=None, **_):
                    raise exc if exc else RuntimeError("retry called")

            return _Stub()

        if (
            decorator_args
            and callable(decorator_args[0])
            and not decorator_kwargs
        ):
            return _wrap(decorator_args[0])
        return _wrap

from config import META_GRAPH_API_VERSION
from src.app.core import audit
from src.app.core.contacts.schemas import ContactCreate
from src.app.core.contacts.service import create_contact
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.dlq import record_dlq as _record_dlq
from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.service import find_subscription
from src.app.core.leads.imports.dedup import find_existing_contact
from src.app.core.leads.ingest import ingest as ingest_lead
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session


logger = logging.getLogger(__name__)


_GRAPH_BASE = "https://graph.facebook.com"
_HTTP_TIMEOUT = 15.0


# --- Celery entrypoint ---------------------------------------------------


@_shared_task(
    bind=True,
    name="src.app.core.integrations.meta.tasks.process_meta_lead",
    autoretry_for=(ConnectionError, TimeoutError),
    max_retries=5,
    retry_backoff=5,
    retry_backoff_max=3600,
    retry_jitter=True,
)
def process_meta_lead(
    self, payload: dict[str, Any]
) -> dict[str, Any]:
    """Sync entrypoint — bridges into async via `asyncio.run`.

    `payload` is the slice the webhook receiver extracted from the
    `entry.changes.value` envelope, with at minimum `leadgen_id`,
    `form_id`, `page_id`. May also carry `ad_id`, `campaign_id`,
    `created_time`.
    """
    try:
        return asyncio.run(process_meta_lead_async(payload=payload))
    except (ConnectionError, TimeoutError) as exc:
        if HAS_CELERY:
            raise self.retry(exc=exc)
        raise


# --- Async body ----------------------------------------------------------


async def process_meta_lead_async(
    *,
    payload: dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Resolve page → integration → subscription, fetch leadgen
    details, create the lead.

    `http_client` is injectable for tests — production opens a fresh
    httpx client per call.

    Outcomes (mirror the Google task for UI consistency):
      `{"status": "created", "lead_id": ...}`,
      `{"status": "duplicate", "lead_id": ...}` (replay of an already-
      processed leadgen_id), or `{"status": "dlq", "reason": ...}`.
    """
    page_id = _extract_page_id(payload)
    leadgen_id = _extract_leadgen_id(payload)
    form_id = _extract_form_id(payload)

    if not page_id or not leadgen_id:
        # Webhook receiver normally guards against this, but a malformed
        # entry slipping through still gets a DLQ row (with the
        # receiver-side `org_id` synthesised; the DLQ surface in
        # Settings will show it under "no integration" for forensics).
        async with async_session() as session:
            await _record_dlq(
                session,
                provider=IntegrationProvider.meta_ads,
                org_id=_fallback_org(),
                integration_id=None,
                payload=payload,
                error_message=(
                    f"payload missing page_id or leadgen_id "
                    f"(page_id={page_id!r}, leadgen_id={leadgen_id!r})"
                ),
            )
        return {"status": "dlq", "reason": "missing_ids"}

    # 1. Resolve page_id → (org_id, integration_id, page_token) via
    # the unscoped cache lookup. The webhook delivery has no JWT, no
    # tenant context — `page_id` is what tells us which tenant.
    async with async_session() as session:
        mapping = await _load_page_token_unscoped(session, page_id)
    if mapping is None:
        async with async_session() as session:
            await _record_dlq(
                session,
                provider=IntegrationProvider.meta_ads,
                org_id=_fallback_org(),
                integration_id=None,
                payload=payload,
                error_message=(
                    f"no cached Page token for page_id={page_id} — "
                    "subscribe the Page or check unsubscribe race."
                ),
            )
        return {"status": "dlq", "reason": "no_page_token"}

    org_id, integration_id, page_token = mapping

    ctx_token = set_context(
        RequestContext(org_id=org_id, user_id=None)
    )
    try:
        async with async_session() as session:
            if not form_id:
                await _record_dlq(
                    session,
                    provider=IntegrationProvider.meta_ads,
                    org_id=org_id,
                    integration_id=integration_id,
                    payload=payload,
                    error_message="payload missing form_id",
                )
                return {"status": "dlq", "reason": "missing_form_id"}

            subscription = await find_subscription(
                session,
                integration_id=integration_id,
                external_form_id=form_id,
            )
            if subscription is None or not subscription.enabled:
                await _record_dlq(
                    session,
                    provider=IntegrationProvider.meta_ads,
                    org_id=org_id,
                    integration_id=integration_id,
                    payload=payload,
                    error_message=(
                        f"no enabled subscription for form {form_id}"
                    ),
                )
                return {"status": "dlq", "reason": "no_subscription"}

            # Idempotency — skip if we've already processed this
            # leadgen_id for this org. Belt-and-suspenders the UNIQUE
            # index from migration 0049.
            existing = await _find_lead_by_external_id(
                session, org_id=org_id, external_lead_id=leadgen_id
            )
            if existing is not None:
                return {"status": "duplicate", "lead_id": str(existing)}

            # 2. Fetch the leadgen details from Meta's Graph API.
            details = await _fetch_leadgen_details(
                leadgen_id=leadgen_id,
                page_token=page_token,
                http_client=http_client,
            )
            if details is None:
                # Treat fetch failures as DLQ-able — Meta either
                # 404'd (lead deleted), 401'd (page token revoked),
                # or 5xx'd (transient — celery's retry would have
                # caught it already; if we're here it persisted).
                await _record_dlq(
                    session,
                    provider=IntegrationProvider.meta_ads,
                    org_id=org_id,
                    integration_id=integration_id,
                    payload=payload,
                    error_message=(
                        f"failed to fetch leadgen {leadgen_id} from Meta"
                    ),
                )
                return {"status": "dlq", "reason": "fetch_failed"}

            # 3. Translate Meta's field_data via the subscription mapping.
            mapped = _apply_mapping(
                subscription.field_mapping or {}, details
            )
            full_name = (mapped.get("contact.full_name") or "").strip()
            phone = mapped.get("contact.phone")
            email = mapped.get("contact.email")
            if not full_name:
                # Meta Lead Forms commonly have FULL_NAME — but the
                # form template is per-form; fall back to phone/email
                # so the contact always has a label.
                full_name = phone or email or "Meta Ads lead"

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
                        source="meta_ads",
                        custom_data=_extract_custom(mapped),
                    ),
                    require_all_required=False,
                )
                contact_id = contact.id

            # Route through the centralised ingest service so the
            # open-lead dedup + round-robin assignment apply uniformly
            # across all five channels.
            result = await ingest_lead(
                session,
                org_id=org_id,
                source=LeadSource.meta_ads,
                contact_id=contact_id,
                lead_payload=LeadCreate(
                    contact_id=contact_id,
                    custom_data=_extract_custom(mapped),
                    source=LeadSource.meta_ads,
                    attribution=_build_attribution(payload, leadgen_id),
                ),
            )

        await audit.log(
            "integration.webhook.received",
            entity_type="lead",
            entity_id=result.lead_id,
            after={
                "provider": "meta_ads",
                "integration_id": str(integration_id),
                "external_form_id": form_id,
                "external_lead_id": leadgen_id,
                "ingest_action": result.action,
                "page_id": page_id,
                "lead_id": str(result.lead_id),
                "contact_id": str(contact_id),
            },
        )
        return {"status": "created", "lead_id": str(result.lead_id)}
    finally:
        reset_context(ctx_token)


# --- payload extractors --------------------------------------------------


def _extract_page_id(payload: dict[str, Any]) -> Optional[str]:
    v = payload.get("page_id")
    return str(v) if v is not None else None


def _extract_leadgen_id(payload: dict[str, Any]) -> Optional[str]:
    v = payload.get("leadgen_id")
    return str(v) if v is not None else None


def _extract_form_id(payload: dict[str, Any]) -> Optional[str]:
    v = payload.get("form_id")
    return str(v) if v is not None else None


def _fallback_org() -> uuid.UUID:
    """For DLQ-on-page-token-missing — we have no real org_id. Use a
    deterministic-ish synthetic so the row lands SOMEWHERE for an
    operator to inspect via `select * from integration_dlq` directly
    (no org's UI shows it because no org owns it)."""
    return uuid.UUID("00000000-0000-0000-0000-000000000000")


def _apply_mapping(
    field_mapping: dict[str, str], details: dict[str, Any]
) -> dict[str, Any]:
    """Translate Meta's `field_data: [{name, values:[v]}, ...]` shape
    through the subscription's `{form_field_name: crm_key}` mapping.

    Meta returns multi-value answers as `values: [...]` arrays even
    for single-answer fields (a list with one element). We take the
    first value; multi-value form types (checkboxes) are uncommon in
    lead forms and a future small task can join them with a separator
    when needed."""
    field_data = details.get("field_data") or []
    result: dict[str, Any] = {}
    for entry in field_data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        values = entry.get("values")
        if not name or not isinstance(values, list) or not values:
            continue
        crm_key = field_mapping.get(name)
        if not crm_key:
            continue
        result[crm_key] = values[0]
    return result


def _extract_custom(mapped: dict[str, Any]) -> dict[str, Any]:
    """Pull `custom_data.*` entries from the mapped row."""
    out: dict[str, Any] = {}
    for k, v in mapped.items():
        if k.startswith("custom_data.") and v not in (None, ""):
            out[k[len("custom_data.") :]] = v
    return out


def _build_attribution(
    payload: dict[str, Any], leadgen_id: str
) -> dict[str, Any]:
    """Spec'd attribution shape:
    `{external_form_id, external_lead_id, page_id, ad_id, campaign_id}`.
    Step-6 reporting + the lead-detail UI both read these keys."""
    attr: dict[str, Any] = {
        "external_form_id": payload.get("form_id"),
        "external_lead_id": leadgen_id,
        "page_id": payload.get("page_id"),
    }
    for opt in ("ad_id", "campaign_id"):
        if payload.get(opt) is not None:
            attr[opt] = payload[opt]
    return attr


# --- internals -----------------------------------------------------------


async def _load_page_token_unscoped(
    session, page_id: str
) -> Optional[tuple[uuid.UUID, uuid.UUID, str]]:
    """Resolve `page_id → (org_id, integration_id, page_token)` by
    raw SQL (bypasses the tenant filter — the receiver has no tenant
    context yet). The webhook HMAC has already authenticated the
    delivery; this lookup tells us which tenant to push onto the
    request context.

    Returns None if no row caches a token for this page_id (Page was
    unsubscribed in the time between Meta queuing the delivery and
    our worker picking it up; rare but worth DLQ-ing for visibility).
    """
    sql = text(
        """
        SELECT org_id, integration_id, page_token_enc
        FROM meta_page_tokens
        WHERE page_id = :page_id
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"page_id": page_id})
    ).mappings().first()
    if row is None:
        return None
    return (
        row["org_id"],
        row["integration_id"],
        decrypt(row["page_token_enc"]),
    )


async def _find_lead_by_external_id(
    session, *, org_id: uuid.UUID, external_lead_id: str
) -> Optional[uuid.UUID]:
    """Idempotency lookup — does this org already have a lead whose
    `attribution->>'external_lead_id'` matches? Uses the partial
    UNIQUE index from 0049."""
    sql = text(
        """
        SELECT id FROM leads
        WHERE org_id = :org_id
          AND attribution->>'external_lead_id' = :ext_id
        LIMIT 1
        """
    )
    return (
        await session.execute(
            sql, {"org_id": str(org_id), "ext_id": external_lead_id}
        )
    ).scalar()


async def _fetch_leadgen_details(
    *,
    leadgen_id: str,
    page_token: str,
    http_client: Optional[httpx.AsyncClient],
) -> Optional[dict[str, Any]]:
    """GET `/{leadgen_id}?fields=id,created_time,field_data,ad_id,
    campaign_id`. Returns the response body on success, None on any
    error — caller routes to DLQ on None.

    We don't raise on transient errors — Celery's retry only fires
    for `(ConnectionError, TimeoutError)`. A 4xx/5xx response here
    means the lead is unfetchable; DLQ is the right home."""
    url = (
        f"{_GRAPH_BASE}/{META_GRAPH_API_VERSION}/{leadgen_id}"
    )
    params = {
        "fields": "id,created_time,field_data,ad_id,campaign_id",
        "access_token": page_token,
    }
    try:
        if http_client is not None:
            response = await http_client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.get(url, params=params)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning(
            "process_meta_lead: leadgen fetch failed (%s)", exc
        )
        # Re-raise as ConnectionError so the Celery autoretry kicks in.
        raise ConnectionError(str(exc)) from exc

    if response.status_code != 200:
        logger.warning(
            "process_meta_lead: leadgen %s returned status=%s",
            leadgen_id,
            response.status_code,
        )
        return None
    try:
        return response.json()
    except ValueError:
        return None


__all__ = [
    "HAS_CELERY",
    "process_meta_lead",
    "process_meta_lead_async",
]
