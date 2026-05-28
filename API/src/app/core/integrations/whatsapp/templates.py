"""Service layer for WhatsApp message-template sync + read.

Two responsibilities:

1. `sync_templates(session)` — pull Meta's `/{waba_id}/message_templates`
   and reconcile with the local `whatsapp_templates` cache:
     - Insert templates Meta returned but we don't have.
     - Update rows whose body / status / category changed in Meta.
     - Delete rows whose (name, language) no longer appears in Meta
       (hard delete — Meta is source of truth; campaigns store template
       name as text, so deletion doesn't break campaign history).
   Returns `{added, updated, removed, total}` counts.

2. `list_templates(session, status, category)` — read for the campaign
   picker (Step 3.5.5). RLS handles org scoping.

Auth model: this module decrypts the bearer token via the existing
`integrations.crypto` helper and uses it to call Meta. Plaintext lives
only inside the async function's call frame; never logged, never
returned to the API surface.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate

logger = logging.getLogger(__name__)


HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15.0)


_VARIABLE_RE = re.compile(r"\{\{(\d+)\}\}")


# --- Meta parsing --------------------------------------------------------


def _extract_components(
    components: list[dict[str, Any]],
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Pull `(body, header_type, header_text, footer_text)` out of
    Meta's `components[]`. Body is required by Meta on every approved
    template; header / footer are optional."""
    body = ""
    header_type: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    for component in components or []:
        ctype = (component.get("type") or "").upper()
        if ctype == "BODY":
            body = str(component.get("text") or "")
        elif ctype == "HEADER":
            header_type = component.get("format")
            header_text = component.get("text")
        elif ctype == "FOOTER":
            footer_text = component.get("text")
    return body, header_type, header_text, footer_text


def _count_variables(body: str) -> int:
    """Distinct `{{n}}` placeholders in the body. Same regex the picker
    + dispatch path use, so counts always agree."""
    return len({int(m) for m in _VARIABLE_RE.findall(body)})


# --- Meta API call -------------------------------------------------------


async def _fetch_all_templates(
    *,
    waba_id: str,
    access_token: str,
    api_version: str,
    http_client_factory: HttpClientFactory,
) -> list[dict[str, Any]]:
    """Walk Meta's `/{waba_id}/message_templates` cursor pagination
    until exhausted. Returns the flat list of template payloads."""
    url: Optional[str] = (
        f"https://graph.facebook.com/{api_version}/{waba_id}"
        "/message_templates?limit=200"
        "&fields=name,language,category,status,components,id"
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    out: list[dict[str, Any]] = []
    async with http_client_factory() as client:
        while url:
            response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                message = _extract_meta_error(response)
                raise WhatsAppNotConnected(
                    f"Meta API rejected the template sync: {message}"
                )
            body = response.json()
            if not isinstance(body, dict):
                raise WhatsAppNotConnected(
                    f"Unexpected Meta response shape: {body!r}"
                )
            data = body.get("data") or []
            if isinstance(data, list):
                out.extend(t for t in data if isinstance(t, dict))
            paging = body.get("paging") or {}
            url = paging.get("next") if isinstance(paging, dict) else None
    return out


def _extract_meta_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
    return f"HTTP {response.status_code}: {response.text[:200]}"


# --- Sync ----------------------------------------------------------------


async def sync_templates(
    session: AsyncSession,
    *,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> dict[str, int]:
    """Reconcile local `whatsapp_templates` with Meta's
    `/{waba_id}/message_templates`. Returns `{added, updated, removed,
    total}` counts.

    Raises `WhatsAppNotConnected` if the active org has no connected
    integration — the router maps this to HTTP 409. Same error surfaces
    if Meta rejects the call mid-sync."""
    bundle = await get_active_config(session)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. "
            "Connect it in Settings → Integrations."
        )
    integration, config = bundle
    if integration.access_token_enc is None:
        raise WhatsAppNotConnected(
            "Stored credentials are missing; reconnect required."
        )
    plaintext_token = decrypt(integration.access_token_enc)

    meta_templates = await _fetch_all_templates(
        waba_id=config.waba_id,
        access_token=plaintext_token,
        api_version=config.api_version,
        http_client_factory=http_client_factory,
    )

    existing_rows = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.integration_id == integration.id
            )
        )
    ).scalars().all()
    by_key: dict[tuple[str, str], WhatsAppTemplate] = {
        (row.name, row.language): row for row in existing_rows
    }
    seen_keys: set[tuple[str, str]] = set()

    now = datetime.now(timezone.utc)
    added = 0
    updated = 0

    for meta_row in meta_templates:
        name = meta_row.get("name")
        language = meta_row.get("language")
        if not name or not language:
            # Skip malformed rows from Meta — should never happen for
            # approved templates, but the contract is best-effort.
            continue
        body, header_type, header_text, footer_text = _extract_components(
            meta_row.get("components") or []
        )
        category = meta_row.get("category") or "UTILITY"
        status_value = meta_row.get("status") or "PENDING"
        variable_count = _count_variables(body)
        meta_template_id = meta_row.get("id")

        key = (name, language)
        seen_keys.add(key)

        existing = by_key.get(key)
        if existing is None:
            session.add(
                WhatsAppTemplate(
                    org_id=integration.org_id,
                    integration_id=integration.id,
                    name=name,
                    language=language,
                    category=category,
                    status=status_value,
                    body=body,
                    header_type=header_type,
                    header_text=header_text,
                    footer_text=footer_text,
                    variable_count=variable_count,
                    meta_template_id=meta_template_id,
                    last_synced_at=now,
                )
            )
            added += 1
        else:
            existing.category = category
            existing.status = status_value
            existing.body = body
            existing.header_type = header_type
            existing.header_text = header_text
            existing.footer_text = footer_text
            existing.variable_count = variable_count
            existing.meta_template_id = meta_template_id
            existing.last_synced_at = now
            updated += 1

    removed = 0
    for key, row in by_key.items():
        if key not in seen_keys:
            await session.delete(row)
            removed += 1

    await session.commit()

    await audit.log(
        "integration.whatsapp.templates_synced",
        entity_type="integration",
        entity_id=integration.id,
        after={
            "added": added,
            "updated": updated,
            "removed": removed,
            "total": added + updated,
        },
    )

    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "total": added + updated,
    }


# --- List ----------------------------------------------------------------


async def list_templates(
    session: AsyncSession,
    *,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> list[WhatsAppTemplate]:
    """Templates for the active org. RLS handles org scoping; optional
    `status` / `category` filters narrow the picker view (e.g. only
    APPROVED + MARKETING for the campaign create-modal)."""
    stmt = select(WhatsAppTemplate).order_by(
        WhatsAppTemplate.category, WhatsAppTemplate.name
    )
    if status is not None:
        stmt = stmt.where(WhatsAppTemplate.status == status)
    if category is not None:
        stmt = stmt.where(WhatsAppTemplate.category == category)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


__all__ = [
    "list_templates",
    "sync_templates",
]
