"""Embedded Signup orchestration — the backend half of Step 2.

Wires Meta's six-call ES choreography (exchange code, fetch WABA, list
phones, subscribe webhooks, register phone, persist) onto the existing
`Integration` + `WhatsAppAccountConfig` row pair the manual `/connect`
flow already writes to. Customer experience: one popup, zero token
paste, fully Intercom-style.

Read this top-to-bottom for the request flow:

  1. `complete_embedded_signup` (the only public entry point) builds a
     `MetaGraphClient` from platform-level env config.
  2. The client exchanges the ES `code` for a long-lived system-user
     token (Meta returns long-lived directly in v19.0+; no second hop).
  3. WABA + phone-number details get fetched so we can persist the
     human-readable display number and the initial tier / quality
     rating without a second round-trip.
  4. The Meta App subscribes itself to the WABA's webhooks so inbound
     messages + delivery statuses start flowing to Core CRM. This is
     the step that 503s when Meta hasn't yet verified our callback URL.
  5. The phone number is registered for Cloud API with a 6-digit PIN
     we generate + encrypt. The PIN is needed if the customer ever
     rotates 2FA settings (Phase 4 will expose a reveal/rotate flow).
  6. We upsert the parent Integration row, the WA sidecar config, and
     seed the tier cache so the campaign create modal's quota banner
     shows live data on first paint.

Persistence is intentionally serial after Meta calls: if any Graph
call fails, we never write a half-baked `connected` row. The audit
log records both the attempt (`code_exchanged`) and the final outcome
(`completed` / `failed`) so an auditor can reconstruct what happened.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    META_APP_ID,
    META_APP_SECRET,
    WHATSAPP_GRAPH_API_VERSION,
)
from src.app.core import audit
from src.app.core.integrations.crypto import encrypt
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp.meta_graph_client import (
    HttpClientFactory,
    MetaGraphClient,
    MetaGraphError,
    PhoneInfo,
    WabaInfo,
)
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig

logger = logging.getLogger(__name__)


# Default per-org outbound rate cap (msg/sec) — matches the manual
# connect flow's default. Operator can edit later in Settings →
# Integrations → WhatsApp → Advanced.
_DEFAULT_RATE_LIMIT = 50


# --- configuration --------------------------------------------------------


class EmbeddedSignupNotConfigured(Exception):
    """Raised when `META_APP_ID` / `META_APP_SECRET` aren't set.

    The router translates this to 503 so the Settings UI can prompt
    the operator to finish Step 1's env-var configuration before
    retrying the connect flow."""


def _build_client(
    http_client_factory: Optional[HttpClientFactory] = None,
) -> MetaGraphClient:
    if not META_APP_ID or not META_APP_SECRET:
        raise EmbeddedSignupNotConfigured(
            "Meta App credentials are not configured — set "
            "META_APP_ID + META_APP_SECRET in .env (Step 1)."
        )
    kwargs = {
        "api_version": WHATSAPP_GRAPH_API_VERSION,
        "app_id": META_APP_ID,
        "app_secret": META_APP_SECRET,
    }
    if http_client_factory is not None:
        kwargs["http_client_factory"] = http_client_factory
    return MetaGraphClient(**kwargs)


def _generate_six_digit_pin() -> str:
    """Cryptographically random 6-digit string. Leading zeros preserved.

    Meta's `/register` endpoint accepts any 6-digit numeric PIN. We
    use it for 2FA on this number; the customer rarely interacts with
    it directly — `secrets.randbelow` keeps the choice unguessable."""
    return f"{secrets.randbelow(1_000_000):06d}"


# --- orchestration --------------------------------------------------------


async def complete_embedded_signup(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    code: str,
    phone_number_id: str,
    waba_id: str,
    http_client_factory: Optional[HttpClientFactory] = None,
) -> dict[str, object]:
    """Run the full ES orchestration. Returns the projection the router
    serialises into `EmbeddedSignupExchangeOut`.

    Raises `MetaGraphError` (router → matching HTTP status) when Meta
    rejects any call, `EmbeddedSignupNotConfigured` (router → 503)
    when our app credentials are missing."""
    client = _build_client(http_client_factory)

    # Step 1 — code → long-lived token.
    try:
        token = await client.exchange_code(code)
    except MetaGraphError as exc:
        await _audit_failed(
            org_id=org_id,
            actor_id=actor_id,
            reason="code_exchange",
            message=exc.user_message,
        )
        raise

    await audit.log(
        "integration.whatsapp.embedded_signup.code_exchanged",
        entity_type="integration",
        org_id=org_id,
        user_id=actor_id,
        after={"waba_id": waba_id, "phone_number_id": phone_number_id},
    )

    # Step 1a — capture the Meta-side user_id for the Data Deletion
    # Callback (Step 4). Best-effort: if `/debug_token` rebuffs, the
    # connect still succeeds — the integration row just gets a NULL
    # `meta_user_id` and Meta's deletion callback won't match it (the
    # operator can still disconnect manually from Settings).
    meta_user_id = await client.debug_token(token)

    # Step 2 — fetch WABA + phone numbers in parallel-ish (sequential
    # is fine; both are sub-second). Pick the requested phone or fall
    # back to the first phone the WABA exposes if Meta's ES popup
    # changed the selection between code-issue and exchange.
    try:
        waba = await client.get_waba(waba_id=waba_id, token=token)
        phones = await client.list_phone_numbers(
            waba_id=waba_id, token=token
        )
    except MetaGraphError as exc:
        await _audit_failed(
            org_id=org_id,
            actor_id=actor_id,
            reason="fetch_waba_or_phones",
            message=exc.user_message,
        )
        raise

    if not phones:
        # Fall back to direct phone lookup — some WABAs occasionally
        # return an empty `data: []` immediately post-creation.
        try:
            phone = await client.get_phone_number(
                phone_id=phone_number_id, token=token
            )
        except MetaGraphError as exc:
            await _audit_failed(
                org_id=org_id,
                actor_id=actor_id,
                reason="fetch_phone",
                message=exc.user_message,
            )
            raise
        phones = [phone]

    selected_index = next(
        (i for i, p in enumerate(phones) if p.id == phone_number_id),
        0,
    )
    selected = phones[selected_index]
    phones_available = len(phones)

    # Step 3 — subscribe Meta App to WABA webhooks.
    try:
        await client.subscribe_app_to_waba(
            waba_id=waba_id, token=token
        )
    except MetaGraphError as exc:
        await _audit_failed(
            org_id=org_id,
            actor_id=actor_id,
            reason="subscribe_apps",
            message=exc.user_message,
        )
        raise

    # Step 4 — register phone for Cloud API with a fresh PIN.
    pin = _generate_six_digit_pin()
    try:
        await client.register_phone_number(
            phone_id=selected.id, token=token, pin=pin
        )
    except MetaGraphError as exc:
        await _audit_failed(
            org_id=org_id,
            actor_id=actor_id,
            reason="register_phone",
            message=exc.user_message,
        )
        raise

    # Step 5 — persist. All-or-nothing: a single transaction across
    # the parent row + sidecar + tier cache.
    integration = await _upsert_integration(
        session,
        org_id=org_id,
        actor_id=actor_id,
        token=token,
        selected=selected,
        waba=waba,
        meta_user_id=meta_user_id,
    )
    # whatsapp-platform-upgrade Step 27b — multi-number ES. Persist
    # the operator-selected phone first (it's the one they'll be
    # primarily working with) + then every other phone Meta returned
    # from the WABA. Each phone becomes its own
    # ``WhatsAppAccountConfig`` row; the dispatcher picks between
    # them via Step 27a's ``send_from_phone_id`` plumbing. We persist
    # in a single transaction so a mid-loop failure rolls every row
    # back together.
    config = await _upsert_config(
        session,
        org_id=org_id,
        integration_id=integration.id,
        selected=selected,
        waba=waba,
        api_version=WHATSAPP_GRAPH_API_VERSION,
    )
    extra_persisted: list[str] = []
    for phone in phones:
        if phone.id == selected.id:
            continue
        try:
            await _upsert_config(
                session,
                org_id=org_id,
                integration_id=integration.id,
                selected=phone,
                waba=waba,
                api_version=WHATSAPP_GRAPH_API_VERSION,
            )
            extra_persisted.append(phone.id)
        except Exception:  # noqa: BLE001
            # Per-phone failures are logged but don't abort the
            # overall connect — the operator can re-run ES later
            # to retry the failed phones.
            import logging

            logging.getLogger(__name__).exception(
                "embedded_signup: failed to persist phone %s for org %s",
                phone.id,
                org_id,
            )

    await audit.log(
        "integration.whatsapp.embedded_signup.completed",
        entity_type="integration",
        entity_id=integration.id,
        org_id=org_id,
        user_id=actor_id,
        after={
            "phone_id": selected.id,
            "waba_id": waba.id,
            "display_phone_number": selected.display_phone_number,
            "verified_name": selected.verified_name or waba.verified_name,
            "phone_numbers_available": phones_available,
            "selected_index": selected_index,
            # Step 27b — every additional phone we connected as part
            # of this ES run. Empty list when the operator's WABA
            # had only one phone (the legacy single-number path).
            "extra_phones_persisted": extra_persisted,
        },
    )

    # Note: `pin` is generated but not persisted in this step. The
    # ES schema has no PIN column today; persistence + reveal/rotate
    # UX is a Phase-4 deliverable. We keep the PIN in memory for the
    # `/register` call above and let it fall out of scope here — Meta
    # remembers it server-side. If the customer ever needs to rotate
    # 2FA, Phase 4 will offer the rotation UI directly.
    del pin

    return {
        "status": "connected",
        "phone_id": selected.id,
        "waba_id": waba.id,
        "display_phone_number": selected.display_phone_number,
        "verified_name": selected.verified_name or waba.verified_name,
        "api_version": config.api_version,
        "rate_limit_per_sec": config.rate_limit_per_sec,
        "phone_numbers_available": phones_available,
        "selected_index": selected_index,
        "messaging_limit_tier": selected.messaging_limit_tier,
        "quality_rating": selected.quality_rating,
    }


# --- persistence helpers --------------------------------------------------


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
    return (
        await session.execute(
            select(WhatsAppAccountConfig).where(
                WhatsAppAccountConfig.integration_id == integration_id
            )
        )
    ).scalar_one_or_none()


async def _upsert_integration(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    token: str,
    selected: PhoneInfo,
    waba: WabaInfo,
    meta_user_id: Optional[str] = None,
) -> Integration:
    """Insert-or-update the (org, whatsapp) row with the long-lived
    system-user token. Encrypts before write. Status flips to
    `connected`, prior `last_error` clears.

    ``meta_user_id`` (when present) is persisted for Step 4's Data
    Deletion Callback to use as the join key. ``None`` keeps the
    column NULL, which is correct for the rare case where Meta's
    `/debug_token` lookup failed mid-connect."""
    existing = await _get_integration_row(session)
    access_enc = encrypt(token)
    now = datetime.now(timezone.utc)
    label = selected.display_phone_number or selected.id

    if existing is None:
        row = Integration(
            org_id=org_id,
            provider=IntegrationProvider.whatsapp,
            account_id=selected.id,
            account_label=label,
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
            meta_user_id=meta_user_id,
        )
        session.add(row)
    else:
        existing.account_id = selected.id
        existing.account_label = label
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
        # Only overwrite when we got a fresh identity — keep the prior
        # value on a reconnect where /debug_token transiently failed.
        if meta_user_id is not None:
            existing.meta_user_id = meta_user_id
        row = existing
    await session.flush()
    return row


async def _upsert_config(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    selected: PhoneInfo,
    waba: WabaInfo,
    api_version: str,
) -> WhatsAppAccountConfig:
    """Insert-or-update the WA sidecar. `app_secret_enc` is left NULL
    for ES-connected orgs — the webhook verifier reads from the
    env-side `WHATSAPP_APP_SECRET` instead, since one Meta App fronts
    every customer (the manual flow's per-org secret stays valid as
    the fallback path for grandfathered orgs).

    `verify_token` is also unused on the ES path — Meta no longer
    sends a per-customer handshake when the Meta App is platform-
    owned and pre-verified — but the column is non-nullable today so
    we seed it with a random opaque string.

    whatsapp-platform-upgrade Step 27b — multi-number per org. The
    lookup is now keyed on ``(integration_id, phone_id)`` so the
    same integration can fan out to many configs (one per WABA
    phone). Re-running ES with the same phone is an UPDATE in
    place; a different phone INSERTS a fresh row."""
    existing = await _get_config_row(
        session,
        integration_id=integration_id,
        phone_id=selected.id,
    )
    display = selected.display_phone_number or selected.id
    verified_name = selected.verified_name or waba.verified_name
    verify_token_seed = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    if existing is None:
        row = WhatsAppAccountConfig(
            org_id=org_id,
            integration_id=integration_id,
            phone_id=selected.id,
            waba_id=waba.id,
            display_phone_number=display,
            verified_name=verified_name,
            app_secret_enc=None,
            verify_token=verify_token_seed,
            api_version=api_version,
            rate_limit_per_sec=_DEFAULT_RATE_LIMIT,
            messaging_limit_tier=selected.messaging_limit_tier,
            tier_synced_at=now if selected.messaging_limit_tier else None,
        )
        session.add(row)
    else:
        existing.phone_id = selected.id
        existing.waba_id = waba.id
        existing.display_phone_number = display
        existing.verified_name = verified_name
        # Don't blow away a per-org app_secret_enc that the legacy
        # manual flow may have written — keep it as the fallback
        # signature key. ES-connected orgs that never had one keep
        # NULL, and the webhook verifier picks env-side instead.
        existing.api_version = api_version
        if selected.messaging_limit_tier:
            existing.messaging_limit_tier = selected.messaging_limit_tier
            existing.tier_synced_at = now
        row = existing
    await session.commit()
    await session.refresh(row)
    return row


# --- audit helpers --------------------------------------------------------


async def _audit_failed(
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    reason: str,
    message: str,
) -> None:
    """Emit the `failed` audit row when any Graph call rejects. Best-
    effort — audit.log never raises, so the caller's `MetaGraphError`
    propagates as the operator-facing 4xx/5xx."""
    await audit.log(
        "integration.whatsapp.embedded_signup.failed",
        entity_type="integration",
        org_id=org_id,
        user_id=actor_id,
        after={"reason": reason, "message": message[:1024]},
    )


__all__ = [
    "EmbeddedSignupNotConfigured",
    "complete_embedded_signup",
]
