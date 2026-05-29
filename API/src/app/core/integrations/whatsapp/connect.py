"""Service layer for the WhatsApp Business Account connect surface.

Responsibilities:

1. `connect_account` — validate the operator-supplied credentials by
   calling Meta's Graph API (`GET /{phone_id}?fields=...`), then on
   success upsert the parent `Integration` row + the WA-specific
   `WhatsAppAccountConfig` sidecar in a single transaction. Both
   bearer token (parent row's `access_token_enc`) and app_secret
   (sidecar's `app_secret_enc`) are encrypted via the existing
   `integrations.crypto` Fernet helper.
2. `disconnect_account` — null the parent's tokens + flip status to
   `disconnected`. The sidecar row stays so a reconnect can pre-fill
   the phone_id / waba_id history (the bearer token isn't there to
   leak; only WA-routing identifiers).
3. `test_connection` — ping Meta with stored credentials; flip the
   parent row to `error` + persist `last_error` if Meta rejects.
4. `get_status` / `get_active_config` — read-side helpers the router
   and (later) the dispatch path use.

The Meta HTTP call is injectable via `http_client_factory` so unit
tests can plug in a stubbed `httpx.AsyncClient`. The factory matches
the same convention the WhatsApp adapter uses (`whatsapp.py`).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.crypto import decrypt, encrypt
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig
from src.app.core.integrations.whatsapp.schemas import WhatsAppConnectIn

logger = logging.getLogger(__name__)

HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0)


# --- read helpers --------------------------------------------------------


async def _get_integration_row(
    session: AsyncSession,
) -> Optional[Integration]:
    """Return the active tenant's WhatsApp `Integration` row, or None."""
    return (
        await session.execute(
            select(Integration).where(
                Integration.provider == IntegrationProvider.whatsapp
            )
        )
    ).scalar_one_or_none()


async def _get_config_row(
    session: AsyncSession, *, integration_id: uuid.UUID
) -> Optional[WhatsAppAccountConfig]:
    """Return the WA sidecar row keyed by `integration_id`, or None."""
    return (
        await session.execute(
            select(WhatsAppAccountConfig).where(
                WhatsAppAccountConfig.integration_id == integration_id
            )
        )
    ).scalar_one_or_none()


async def get_active_config(
    session: AsyncSession,
) -> Optional[tuple[Integration, WhatsAppAccountConfig]]:
    """Resolve the active tenant's connected WhatsApp config. Returns
    `(integration, config)` if the org has a `connected` row with a
    populated sidecar; None otherwise.

    Callers in dispatch / webhook paths use this to decide whether to
    fall through to env-var defaults (Step 3.5.3) or hard-fail."""
    integration = await _get_integration_row(session)
    if integration is None or integration.status != IntegrationStatus.connected:
        return None
    config = await _get_config_row(
        session, integration_id=integration.id
    )
    if config is None:
        return None
    return integration, config


async def get_status(session: AsyncSession) -> dict[str, Any]:
    """Projection consumed by `GET /status` + `connect/test` responses.

    Returns the lifecycle state + sidecar display fields. Never returns
    plaintext credentials."""
    integration = await _get_integration_row(session)
    if integration is None:
        return {"status": "disconnected"}
    config = await _get_config_row(
        session, integration_id=integration.id
    )
    payload: dict[str, Any] = {
        "status": integration.status.value,
        "last_error": integration.last_error,
        "connected_at": integration.connected_at,
    }
    if config is not None:
        payload.update(
            {
                "phone_id": config.phone_id,
                "waba_id": config.waba_id,
                "display_phone_number": config.display_phone_number,
                "verified_name": config.verified_name,
                "api_version": config.api_version,
                "rate_limit_per_sec": config.rate_limit_per_sec,
            }
        )
    return payload


# --- Meta validation -----------------------------------------------------


class MetaValidationError(Exception):
    """Raised when Meta rejects the supplied credentials. Message text
    is taken verbatim from Meta's error response so the operator can
    diagnose ("(#190) Invalid OAuth access token", etc.)."""


async def _validate_with_meta(
    *,
    phone_id: str,
    access_token: str,
    api_version: str,
    http_client_factory: HttpClientFactory,
) -> dict[str, Any]:
    """Hit `GET graph.facebook.com/{api_version}/{phone_id}` with the
    operator's bearer token. Returns Meta's JSON body on success.

    Raises `MetaValidationError` with Meta's error message on non-2xx."""
    url = (
        f"https://graph.facebook.com/{api_version}/{phone_id}"
        "?fields=display_phone_number,verified_name"
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    async with http_client_factory() as client:
        response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        message = _extract_meta_error(response)
        raise MetaValidationError(message)
    body = response.json()
    if not isinstance(body, dict):
        raise MetaValidationError(
            f"unexpected meta response shape: {body!r}"
        )
    return body


def _extract_meta_error(response: httpx.Response) -> str:
    """Pull Meta's `error.message` out of the response body, falling
    back to the raw text + status code."""
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return f"Meta API rejected the credentials: {err['message']}"
    return f"HTTP {response.status_code}: {response.text[:200]}"


# --- writes --------------------------------------------------------------


async def connect_account(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    payload: WhatsAppConnectIn,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> dict[str, Any]:
    """Validate creds → upsert Integration + sidecar → return projection.

    Order matters: Meta validation runs BEFORE any DB write so a bad
    token never produces a half-baked `connected` row. On Meta rejection
    we still persist `status=error` + `last_error` so the Settings UI
    can surface the message; the sidecar is NOT created in that path
    (no point caching phone_id from credentials we never accepted)."""
    try:
        meta_payload = await _validate_with_meta(
            phone_id=payload.phone_id,
            access_token=payload.access_token,
            api_version=payload.api_version,
            http_client_factory=http_client_factory,
        )
    except MetaValidationError as exc:
        await _persist_error(
            session,
            org_id=org_id,
            actor_id=actor_id,
            phone_id=payload.phone_id,
            display_label=None,
            error_message=str(exc),
        )
        # Re-raise so the router returns 400 with the same message.
        raise

    display_phone_number = str(
        meta_payload.get("display_phone_number") or payload.phone_id
    )
    verified_name = meta_payload.get("verified_name")
    if verified_name is not None:
        verified_name = str(verified_name)

    integration = await _upsert_integration_row(
        session,
        org_id=org_id,
        actor_id=actor_id,
        access_token=payload.access_token,
        phone_id=payload.phone_id,
        display_label=display_phone_number,
    )
    await _upsert_config_row(
        session,
        org_id=org_id,
        integration_id=integration.id,
        payload=payload,
        display_phone_number=display_phone_number,
        verified_name=verified_name,
    )

    await audit.log(
        "integration.whatsapp.connected",
        entity_type="integration",
        entity_id=integration.id,
        after={
            "phone_id": payload.phone_id,
            "waba_id": payload.waba_id,
            "display_phone_number": display_phone_number,
            "verified_name": verified_name,
        },
    )

    return await get_status(session)


async def _upsert_integration_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    access_token: str,
    phone_id: str,
    display_label: str,
) -> Integration:
    """Insert-or-update the (org, whatsapp) row. Encrypts the bearer
    token before write. Flips status to `connected`, clears any prior
    `last_error`."""
    existing = await _get_integration_row(session)
    access_enc = encrypt(access_token)
    now = datetime.now(timezone.utc)

    if existing is None:
        row = Integration(
            org_id=org_id,
            provider=IntegrationProvider.whatsapp,
            account_id=phone_id,
            account_label=display_label,
            access_token_enc=access_enc,
            refresh_token_enc=None,
            token_expires_at=None,
            scopes=None,
            status=IntegrationStatus.connected,
            last_error=None,
            connected_at=now,
            connected_by=actor_id,
            disconnected_at=None,
            disconnected_by=None,
            webhook_secret=None,
        )
        session.add(row)
    else:
        existing.account_id = phone_id
        existing.account_label = display_label
        existing.access_token_enc = access_enc
        existing.refresh_token_enc = None
        existing.token_expires_at = None
        existing.scopes = None
        existing.status = IntegrationStatus.connected
        existing.last_error = None
        existing.connected_at = now
        existing.connected_by = actor_id
        existing.disconnected_at = None
        existing.disconnected_by = None
        row = existing
    await session.flush()
    return row


async def _upsert_config_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    payload: WhatsAppConnectIn,
    display_phone_number: str,
    verified_name: Optional[str],
) -> WhatsAppAccountConfig:
    """Insert-or-update the WA sidecar row. Encrypts the app secret."""
    existing = await _get_config_row(
        session, integration_id=integration_id
    )
    app_secret_enc = encrypt(payload.app_secret)
    if existing is None:
        row = WhatsAppAccountConfig(
            org_id=org_id,
            integration_id=integration_id,
            phone_id=payload.phone_id,
            waba_id=payload.waba_id,
            display_phone_number=display_phone_number,
            verified_name=verified_name,
            app_secret_enc=app_secret_enc,
            verify_token=payload.verify_token,
            api_version=payload.api_version,
            rate_limit_per_sec=payload.rate_limit_per_sec,
        )
        session.add(row)
    else:
        existing.phone_id = payload.phone_id
        existing.waba_id = payload.waba_id
        existing.display_phone_number = display_phone_number
        existing.verified_name = verified_name
        existing.app_secret_enc = app_secret_enc
        existing.verify_token = payload.verify_token
        existing.api_version = payload.api_version
        existing.rate_limit_per_sec = payload.rate_limit_per_sec
        row = existing
    await session.commit()
    await session.refresh(row)
    return row


async def _persist_error(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    phone_id: str,
    display_label: Optional[str],
    error_message: str,
) -> None:
    """Persist a parent-row failure marker (`status=error`,
    `last_error`) when Meta rejects credentials. Truncates the error
    text to fit `last_error`'s soft cap so a verbose Meta message
    doesn't bloat the row."""
    existing = await _get_integration_row(session)
    truncated = error_message[:1024]
    now = datetime.now(timezone.utc)
    if existing is None:
        row = Integration(
            org_id=org_id,
            provider=IntegrationProvider.whatsapp,
            account_id=phone_id,
            account_label=display_label,
            access_token_enc=None,
            refresh_token_enc=None,
            status=IntegrationStatus.error,
            last_error=truncated,
            connected_by=actor_id,
            disconnected_at=None,
            disconnected_by=None,
            webhook_secret=None,
        )
        session.add(row)
    else:
        existing.status = IntegrationStatus.error
        existing.last_error = truncated
        existing.connected_by = actor_id
        # Keep `connected_at` from the last good connect (if any) so the
        # Settings UI can show "last connected on X, failed on Y".
        if existing.connected_at is None:
            existing.connected_at = now
        row = existing
    await session.commit()
    await audit.log(
        "integration.whatsapp.connect_failed",
        entity_type="integration",
        entity_id=row.id,
        after={"phone_id": phone_id, "error": truncated},
    )


async def disconnect_account(
    session: AsyncSession,
    *,
    actor_id: Optional[uuid.UUID],
) -> Optional[Integration]:
    """Null the bearer token + flip status to `disconnected`. Sidecar
    row stays so reconnect can pre-fill phone_id / waba_id.

    Idempotent — disconnecting an already-disconnected row is a no-op."""
    row = await _get_integration_row(session)
    if row is None:
        return None
    if row.status == IntegrationStatus.disconnected:
        return row
    row.access_token_enc = None
    row.refresh_token_enc = None
    row.status = IntegrationStatus.disconnected
    row.disconnected_at = datetime.now(timezone.utc)
    row.disconnected_by = actor_id
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.whatsapp.disconnected",
        entity_type="integration",
        entity_id=row.id,
    )
    return row


async def test_connection(
    session: AsyncSession,
    *,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> dict[str, Any]:
    """Ping Meta with stored credentials. Updates status + last_error
    based on the response.

    Used by the Settings UI's "Test" button (Step 3.5.2) and any
    pre-dispatch health check we add later."""
    bundle = await get_active_config(session)
    if bundle is None:
        # Try to be helpful — distinguish "never connected" from
        # "disconnected" by re-reading the integration row.
        integration = await _get_integration_row(session)
        if integration is None:
            raise MetaValidationError(
                "WhatsApp is not connected for this org."
            )
        # Disconnected (token nulled) — surface the dedicated message.
        raise MetaValidationError(
            f"WhatsApp is {integration.status.value}; reconnect first."
        )
    integration, config = bundle
    if integration.access_token_enc is None:
        raise MetaValidationError(
            "Stored credentials are missing; reconnect required."
        )
    plaintext_token = decrypt(integration.access_token_enc)
    try:
        await _validate_with_meta(
            phone_id=config.phone_id,
            access_token=plaintext_token,
            api_version=config.api_version,
            http_client_factory=http_client_factory,
        )
    except MetaValidationError as exc:
        integration.status = IntegrationStatus.error
        integration.last_error = str(exc)[:1024]
        await session.commit()
        await session.refresh(integration)
        raise

    # Success → clear any previous error if present.
    if integration.status != IntegrationStatus.connected or integration.last_error:
        integration.status = IntegrationStatus.connected
        integration.last_error = None
        await session.commit()
        await session.refresh(integration)
    return await get_status(session)


# --- webhook routing helpers (Step 3.5.12) ------------------------------


async def find_org_by_phone_id(
    session: AsyncSession, *, phone_id: str
) -> Optional[tuple[Integration, WhatsAppAccountConfig]]:
    """Look up the org that owns a given WhatsApp phone number id.

    Used by the inbound webhook receiver to learn which org's
    credentials to verify the payload against — Meta's webhook payload
    carries `entry[0].changes[0].value.metadata.phone_number_id`,
    which uniquely identifies the destination phone across all orgs.

    Bypasses the ORM tenant filter intentionally: the webhook arrives
    without any tenant context (Meta doesn't send our JWT). The
    `phone_id` IS the routing key. Returns None if no org has this
    phone connected (webhook receiver translates to 404 → integration
    DLQ for forensics).
    """
    from sqlalchemy import text as sql_text

    if not phone_id:
        return None
    sql = sql_text(
        """
        SELECT
            i.id AS i_id, i.org_id, i.provider, i.account_id,
            i.account_label, i.access_token_enc, i.refresh_token_enc,
            i.token_expires_at, i.scopes, i.status, i.last_error,
            i.connected_at, i.connected_by, i.disconnected_at,
            i.disconnected_by, i.updated_at, i.webhook_secret,
            c.id AS c_id, c.phone_id, c.waba_id, c.display_phone_number,
            c.verified_name, c.app_secret_enc, c.verify_token,
            c.api_version, c.created_at AS c_created_at,
            c.updated_at AS c_updated_at
        FROM whatsapp_account_configs c
        JOIN integrations i ON i.id = c.integration_id
        WHERE c.phone_id = :phone_id
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"phone_id": phone_id})
    ).mappings().first()
    if row is None:
        return None
    integration = Integration(
        id=row["i_id"],
        org_id=row["org_id"],
        provider=IntegrationProvider(row["provider"]),
        account_id=row["account_id"],
        account_label=row["account_label"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes=row["scopes"],
        status=IntegrationStatus(row["status"]),
        last_error=row["last_error"],
        connected_at=row["connected_at"],
        connected_by=row["connected_by"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
        updated_at=row["updated_at"],
        webhook_secret=row["webhook_secret"],
    )
    config = WhatsAppAccountConfig(
        id=row["c_id"],
        org_id=row["org_id"],
        integration_id=integration.id,
        phone_id=row["phone_id"],
        waba_id=row["waba_id"],
        display_phone_number=row["display_phone_number"],
        verified_name=row["verified_name"],
        app_secret_enc=row["app_secret_enc"],
        verify_token=row["verify_token"],
        api_version=row["api_version"],
        created_at=row["c_created_at"],
        updated_at=row["c_updated_at"],
    )
    return integration, config


async def find_org_by_verify_token(
    session: AsyncSession, *, verify_token: str
) -> Optional[tuple[Integration, WhatsAppAccountConfig]]:
    """Look up the org whose verify_token matches the one Meta sent on
    the GET-handshake. Same bypass-tenant-filter approach as
    `find_org_by_phone_id` — the handshake carries no other identifier.

    Multiple orgs MAY share a verify_token if operators choose the
    same random string (unlikely but possible). We return the first
    match — the handshake is one-shot at webhook setup, not a security
    boundary; the signature check on subsequent POSTs is what
    isolates orgs."""
    from sqlalchemy import text as sql_text

    if not verify_token:
        return None
    sql = sql_text(
        """
        SELECT c.phone_id
        FROM whatsapp_account_configs c
        WHERE c.verify_token = :vt
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"vt": verify_token})
    ).mappings().first()
    if row is None:
        return None
    return await find_org_by_phone_id(session, phone_id=row["phone_id"])


__all__ = [
    "MetaValidationError",
    "connect_account",
    "disconnect_account",
    "find_org_by_phone_id",
    "find_org_by_verify_token",
    "get_active_config",
    "get_status",
    "test_connection",
]
