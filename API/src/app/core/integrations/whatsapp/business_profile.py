"""Service layer for WhatsApp Business profile editor
(whatsapp-platform-upgrade Step 11).

Owns four jobs:

  * ``get_profile(session)`` — read the local mirror (Meta-side fields
    + Core-CRM business hours / greeting / away). Triggers a one-shot
    Meta refresh on the very first call so the form opens populated.
  * ``update_profile(session, patch)`` — push the supplied fields to
    Meta (``POST /{phone_id}/whatsapp_business_profile``) and mirror
    them locally, plus persist the Core-CRM-only fields (hours,
    greeting, away). Audit-logs the diff per save.
  * ``refresh_from_meta(session)`` — manual Meta GET + local upsert.
  * ``upload_picture(session, file_bytes, mime_type)`` — multipart
    POST to Meta's resumable upload endpoint then attach the handle
    to the profile.

All operations use the same per-org credential resolver as the rest of
the WhatsApp module (``get_active_config`` + ``decrypt``), and rely on
``MetaGraphError`` for typed routing of Meta failures.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import (
    WhatsAppAccountConfig,
)

logger = logging.getLogger(__name__)


HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0)


_META_PROFILE_FIELDS = "about,address,description,email,profile_picture_url,websites,vertical"


class BusinessProfileError(Exception):
    """Typed wrapper for Meta-side business-profile failures.

    `http_status` is the friendly status the router surfaces;
    `user_message` is the operator-facing reason. Mirrors
    ``MetaGraphError`` shape so callers can treat both uniformly."""

    def __init__(self, *, http_status: int, user_message: str) -> None:
        super().__init__(user_message)
        self.http_status = http_status
        self.user_message = user_message


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


# --- Meta calls -----------------------------------------------------------


async def _fetch_profile_from_meta(
    *,
    phone_id: str,
    token: str,
    api_version: str,
    http_client_factory: HttpClientFactory,
) -> dict[str, Any]:
    """``GET /{phone_id}/whatsapp_business_profile?fields=...``.

    Meta wraps the profile in a `data: [{...}]` list — we unwrap to
    the inner dict for caller simplicity. Returns ``{}`` when the
    array is empty (a never-edited profile)."""
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/whatsapp_business_profile"
    async with http_client_factory() as client:
        response = await client.get(
            url,
            params={"fields": _META_PROFILE_FIELDS},
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code >= 400:
        raise BusinessProfileError(
            http_status=502,
            user_message=(f"Meta refused the profile fetch: {_extract_meta_error(response)}"),
        )
    body = response.json() if response.content else {}
    if not isinstance(body, dict):
        return {}
    data = body.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


async def _push_profile_to_meta(
    *,
    phone_id: str,
    token: str,
    api_version: str,
    payload: dict[str, Any],
    http_client_factory: HttpClientFactory,
) -> None:
    """``POST /{phone_id}/whatsapp_business_profile`` with the
    operator's edits. Meta returns ``{success: true}`` on accept;
    anything else surfaces as ``BusinessProfileError``."""
    if not payload:
        return
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/whatsapp_business_profile"
    body = {"messaging_product": "whatsapp", **payload}
    async with http_client_factory() as client:
        response = await client.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code == 429:
        raise BusinessProfileError(
            http_status=429,
            user_message=(
                "Meta rate-limited the profile update — "
                "Meta caps these at ~10 updates/day per phone."
            ),
        )
    if response.status_code >= 400:
        raise BusinessProfileError(
            http_status=400,
            user_message=(f"Meta refused the profile update: {_extract_meta_error(response)}"),
        )


async def _upload_picture_to_meta(
    *,
    phone_id: str,
    token: str,
    api_version: str,
    file_bytes: bytes,
    mime_type: str,
    http_client_factory: HttpClientFactory,
) -> str:
    """Upload the picture as ``image`` media + return the resulting
    Meta media id. The caller then POSTs that media id back to the
    profile endpoint under ``profile_picture_handle``.

    We use the standard ``/{phone_id}/media`` upload (same path Step 5
    uses) rather than the more complex resumable upload — Meta accepts
    PNG/JPEG up to 5MB on this endpoint, which is enough for the
    640×640 profile pic recommendation."""
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/media"
    files = {
        "file": ("profile_picture", file_bytes, mime_type),
        "messaging_product": (None, "whatsapp"),
        "type": (None, mime_type),
    }
    async with http_client_factory() as client:
        response = await client.post(
            url,
            files=files,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code >= 400:
        raise BusinessProfileError(
            http_status=400,
            user_message=(f"Meta refused the picture upload: {_extract_meta_error(response)}"),
        )
    body = response.json()
    media_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(media_id, str) or not media_id:
        raise BusinessProfileError(
            http_status=502,
            user_message="Meta accepted the upload but returned no media id.",
        )
    return media_id


# --- local read / write ---------------------------------------------------


async def _resolve_active_config(
    session: AsyncSession,
    *,
    phone_id: str | None = None,
) -> tuple[Any, WhatsAppAccountConfig]:
    """Pull (integration, config) for the active org. Raises
    ``WhatsAppNotConnected`` mirroring the existing send / sync path.

    whatsapp-platform-upgrade Step 27b — ``phone_id`` selects a
    specific WhatsApp config when the org has multiple connected
    numbers. NULL falls back to the org default (the oldest config
    row), preserving the legacy behaviour for single-number orgs."""
    bundle = await get_active_config(session, phone_id=phone_id)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. Connect it in Settings → Integrations."
        )
    integration, config = bundle
    if integration.access_token_enc is None:
        raise WhatsAppNotConnected("Stored credentials are missing; reconnect required.")
    return integration, config


def _snapshot(config: WhatsAppAccountConfig) -> dict[str, Any]:
    """Diffable snapshot of the editable fields. Used by the audit
    log so the operator can see exactly what changed on every save."""
    return {
        "about": config.profile_about,
        "description": config.profile_description,
        "address": config.profile_address,
        "email": config.profile_email,
        "websites": list(config.profile_websites or []),
        "vertical": config.profile_vertical,
        "profile_picture_url": config.profile_picture_url,
        "business_hours": list(config.business_hours or []),
        "greeting_message": config.greeting_message,
        "away_message": config.away_message,
    }


# --- public API -----------------------------------------------------------


async def get_profile(
    session: AsyncSession,
    *,
    phone_id: str | None = None,
    auto_refresh: bool = True,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> WhatsAppAccountConfig:
    """Return the local profile row. When `auto_refresh` and the row
    has never been synced, do a one-shot Meta GET so the form opens
    populated. Failures are non-fatal — the form just opens empty.

    Step 27b — ``phone_id`` selects the multi-number config; NULL
    falls back to the org default."""
    _, config = await _resolve_active_config(session, phone_id=phone_id)
    if auto_refresh and config.profile_last_synced_at is None:
        try:
            await refresh_from_meta(
                session,
                phone_id=phone_id,
                http_client_factory=http_client_factory,
            )
            _, config = await _resolve_active_config(session, phone_id=phone_id)
        except BusinessProfileError:
            logger.exception("first-open Meta refresh failed; opening empty form")
    return config


async def refresh_from_meta(
    session: AsyncSession,
    *,
    phone_id: str | None = None,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> WhatsAppAccountConfig:
    """Pull every Meta-side field + persist to the local row.

    Doesn't touch the Core-CRM-only fields (hours, greeting, away).
    Stamps `profile_last_synced_at` so the UI can render "Synced N
    minutes ago".

    Step 27b — ``phone_id`` selects which connected phone's profile
    to refresh; NULL falls back to the org default."""
    integration, config = await _resolve_active_config(session, phone_id=phone_id)
    token = decrypt(integration.access_token_enc)

    meta_data = await _fetch_profile_from_meta(
        phone_id=config.phone_id,
        token=token,
        api_version=config.api_version,
        http_client_factory=http_client_factory,
    )

    before = _snapshot(config)
    config.profile_about = meta_data.get("about") or None
    config.profile_description = meta_data.get("description") or None
    config.profile_address = meta_data.get("address") or None
    config.profile_email = meta_data.get("email") or None
    websites = meta_data.get("websites")
    config.profile_websites = list(websites) if isinstance(websites, list) else None
    config.profile_vertical = meta_data.get("vertical") or None
    config.profile_picture_url = meta_data.get("profile_picture_url") or None
    config.profile_last_synced_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(config)

    await audit.log(
        "integration.whatsapp.profile_refreshed",
        entity_type="whatsapp_account",
        entity_id=config.id,
        before=before,
        after=_snapshot(config),
    )
    return config


async def update_profile(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    patch: dict[str, Any],
    phone_id: str | None = None,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> WhatsAppAccountConfig:
    """Apply the operator's edits to Meta + the local mirror.

    Meta-side fields go through ``_push_profile_to_meta``; Core-CRM-
    only fields (hours / greeting / away) write straight to the row.
    Empty patches are a no-op (no Meta call, no audit row).

    Step 27b — ``phone_id`` selects which connected phone's profile
    to edit. NULL falls back to the org default."""
    integration, config = await _resolve_active_config(session, phone_id=phone_id)
    token = decrypt(integration.access_token_enc)

    # Split the patch into Meta-bound + Core-only fields. Meta cares
    # only about its documented keys; the rest stay local.
    meta_payload: dict[str, Any] = {}
    if "about" in patch:
        meta_payload["about"] = patch["about"] or ""
    if "description" in patch:
        meta_payload["description"] = patch["description"] or ""
    if "address" in patch:
        meta_payload["address"] = patch["address"] or ""
    if "email" in patch:
        meta_payload["email"] = patch["email"] or ""
    if "websites" in patch:
        websites = patch["websites"] or []
        meta_payload["websites"] = list(websites)
    if "vertical" in patch:
        meta_payload["vertical"] = patch["vertical"] or "UNDEFINED"

    if meta_payload:
        await _push_profile_to_meta(
            phone_id=config.phone_id,
            token=token,
            api_version=config.api_version,
            payload=meta_payload,
            http_client_factory=http_client_factory,
        )

    before = _snapshot(config)

    # Mirror Meta-bound fields locally.
    if "about" in patch:
        config.profile_about = patch["about"] or None
    if "description" in patch:
        config.profile_description = patch["description"] or None
    if "address" in patch:
        config.profile_address = patch["address"] or None
    if "email" in patch:
        config.profile_email = patch["email"] or None
    if "websites" in patch:
        config.profile_websites = list(patch["websites"] or [])
    if "vertical" in patch:
        config.profile_vertical = patch["vertical"] or None

    # Core-CRM-only fields.
    if "business_hours" in patch:
        config.business_hours = (
            list(patch["business_hours"]) if patch["business_hours"] is not None else None
        )
    if "greeting_message" in patch:
        config.greeting_message = patch["greeting_message"] or None
    if "away_message" in patch:
        config.away_message = patch["away_message"] or None

    if meta_payload:
        config.profile_last_synced_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(config)

    after = _snapshot(config)
    if before != after:
        await audit.log(
            "integration.whatsapp.profile_updated",
            entity_type="whatsapp_account",
            entity_id=config.id,
            user_id=actor_id,
            before=before,
            after=after,
        )
    return config


async def upload_picture(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    file_bytes: bytes,
    mime_type: str,
    phone_id: str | None = None,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> WhatsAppAccountConfig:
    """Upload the operator's picture to Meta + attach the returned
    handle to the profile. Meta requires JPEG/PNG; we accept the
    same here. The DB row picks up `profile_picture_url` on the next
    refresh — Meta doesn't return the public URL synchronously.

    Step 27b — ``phone_id`` selects which phone's profile picture
    to update."""
    if mime_type not in ("image/jpeg", "image/png"):
        raise BusinessProfileError(
            http_status=400,
            user_message="Profile picture must be JPEG or PNG.",
        )
    if len(file_bytes) > 5 * 1024 * 1024:
        raise BusinessProfileError(
            http_status=413,
            user_message="Profile picture must be 5 MB or smaller.",
        )

    integration, config = await _resolve_active_config(session, phone_id=phone_id)
    token = decrypt(integration.access_token_enc)

    handle = await _upload_picture_to_meta(
        phone_id=config.phone_id,
        token=token,
        api_version=config.api_version,
        file_bytes=file_bytes,
        mime_type=mime_type,
        http_client_factory=http_client_factory,
    )
    # Push the handle to the profile so Meta promotes it to the
    # public-facing `profile_picture_url`.
    await _push_profile_to_meta(
        phone_id=config.phone_id,
        token=token,
        api_version=config.api_version,
        payload={"profile_picture_handle": handle},
        http_client_factory=http_client_factory,
    )
    # Re-fetch so we pick up the new public URL.
    return await refresh_from_meta(session, http_client_factory=http_client_factory)


__all__ = [
    "BusinessProfileError",
    "get_profile",
    "refresh_from_meta",
    "update_profile",
    "upload_picture",
]
