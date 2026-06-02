"""Pydantic v2 schemas for the integrations API surface.

`IntegrationRead` is the public projection — **deliberately omits the
`*_enc` ciphertext columns** so tokens cannot leak via the API even if
a caller bypasses the router and serialises the SQLAlchemy row directly.

`IntegrationUpsert` is the internal write shape — used by the OAuth
callback handlers (Step 2 + 4) to pass plaintext tokens into
`service.upsert()`. It's NEVER deserialised from an HTTP body; the
router has no PUT/POST endpoint that accepts it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from config import API_BASE_URL

from src.app.shared.schemas import ORMModel, PaginatedResponse, TimestampedOrgScopedOut


# Mirrors the SQLAlchemy `IntegrationProvider` / `IntegrationStatus`
# enums as Literals so schema consumers don't have to import the ORM.
IntegrationProviderLiteral = Literal["google_ads", "meta_ads", "whatsapp"]
IntegrationStatusLiteral = Literal[
    "connected", "disconnected", "expired", "error"
]


class IntegrationRead(ORMModel):
    """Row projection for `GET /api/v1/integrations`. Encrypted-token
    columns (`*_enc`) are intentionally absent — they aren't declared,
    so a router accidentally returning the raw ORM row can't leak
    ciphertext through this schema.

    `webhook_secret` IS exposed — it's the secret an admin pastes into
    the ad platform's webhook config, so they need to see it; tokens
    are different (the admin never types them anywhere). The Settings
    UI displays it inside the constructed `webhook_url`."""

    id: uuid.UUID
    org_id: uuid.UUID
    provider: IntegrationProviderLiteral
    account_id: Optional[str]
    account_label: Optional[str]
    token_expires_at: Optional[datetime]
    scopes: Optional[list[str]]
    status: IntegrationStatusLiteral
    last_error: Optional[str]
    connected_at: Optional[datetime]
    connected_by: Optional[uuid.UUID]
    disconnected_at: Optional[datetime]
    disconnected_by: Optional[uuid.UUID]
    updated_at: datetime
    # Per-tenant webhook URL discriminator (Google) — admin pastes it
    # into the Google Ads UI. Meta uses a single env-level URL with no
    # per-tenant component; `webhook_secret` stays None for Meta rows.
    webhook_secret: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def webhook_url(self) -> Optional[str]:
        """Provider-aware webhook URL the Settings UI surfaces.

        - `google_ads` (connected, has secret) →
          `{API_BASE_URL}/api/v1/integrations/google/webhook/v1/<secret>`.
          Admin pastes into each Google Ads Lead Form's webhook field.
        - `meta_ads` (connected) → `{API_BASE_URL}/api/v1/integrations/meta/webhook`.
          One URL per environment; admins configure it ONCE in the
          Meta app dashboard, NOT per integration (Meta's webhook
          model is push-subscription, not pull).
        - otherwise → None.
        """
        if self.provider == "google_ads" and self.webhook_secret:
            return (
                f"{API_BASE_URL}/api/v1/integrations/google/webhook/v1/"
                f"{self.webhook_secret}"
            )
        if self.provider == "meta_ads" and self.status == "connected":
            return f"{API_BASE_URL}/api/v1/integrations/meta/webhook"
        return None


class IntegrationUpsert(BaseModel):
    """Internal write shape — passed from the OAuth callback handlers
    into `service.upsert()`. NOT exposed as an HTTP request body."""

    provider: IntegrationProviderLiteral
    account_id: Optional[str] = Field(default=None, max_length=128)
    account_label: Optional[str] = Field(default=None, max_length=255)
    access_token: str = Field(min_length=1)
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)


class IntegrationSubscriptionRead(TimestampedOrgScopedOut):
    """Subscription row projection — what the Settings UI shows in the
    form-picker list. `field_mapping` is exposed in full so the editor
    in Step 8 can drive its UI without a second fetch."""

    id: uuid.UUID
    integration_id: uuid.UUID
    external_form_id: str
    external_form_label: Optional[str]
    field_mapping: dict
    enabled: bool


class IntegrationSubscriptionCreate(BaseModel):
    """Settings UI: "subscribe to this form, with this mapping".

    `field_mapping` is `{ad_field_name: "contact.full_name"}` /
    `"contact.phone"` / `"contact.email"` / `"custom_data.<key>"`
    — same target shape as the bulk-import mapping. Empty mapping is
    allowed at create time; the editor in Step 8 fills it in."""

    integration_id: uuid.UUID
    external_form_id: str = Field(min_length=1, max_length=128)
    external_form_label: Optional[str] = Field(default=None, max_length=255)
    field_mapping: dict = Field(default_factory=dict)
    enabled: bool = True


class IntegrationSubscriptionUpdate(BaseModel):
    """Partial-update shape for the mapping editor + enable/disable
    toggle in the Settings UI. `external_form_id` is immutable — to
    point at a different form, delete + recreate."""

    external_form_label: Optional[str] = Field(default=None, max_length=255)
    field_mapping: Optional[dict] = None
    enabled: Optional[bool] = None


class IntegrationDLQRead(ORMModel):
    """DLQ row projection. The Settings page lists these with a
    "Replay" button per row; `replayed_at` populates once the row has
    been re-enqueued (and stays populated forever so an Owner can see
    which payloads have already been retried)."""

    id: uuid.UUID
    org_id: uuid.UUID
    integration_id: Optional[uuid.UUID]
    provider: IntegrationProviderLiteral
    payload: dict
    error_message: str
    retries_attempted: int
    created_at: datetime
    replayed_at: Optional[datetime]
    replayed_by: Optional[uuid.UUID]


IntegrationDLQListResponse = PaginatedResponse[IntegrationDLQRead]


class SubscriptionMappingUpdate(BaseModel):
    """Step-8 endpoint body: full replacement of a subscription's
    `field_mapping`. Keys are ad-platform field names (Google's
    `column_name`, Meta's form field `name`); values are CRM target
    keys validated by the router against `leads.imports.targets`.

    Using a dict (not a list of pairs) matches the JSONB column shape
    and lets the editor send one POST per save. Empty dict is allowed
    — means "drop all fields" and the worker will DLQ inbound payloads
    until the operator restores at least one mapping."""

    model_config = ConfigDict(extra="forbid")

    mapping: dict[str, str] = Field(default_factory=dict)


class ProviderDeliveryStatus(BaseModel):
    """Per-provider row inside `IntegrationStatusResponse`. Drives
    the Settings dashboard panel: green dot if recent delivery,
    amber if DLQ count > 0, none if neither connected nor delivered."""

    provider: IntegrationProviderLiteral
    status: IntegrationStatusLiteral
    last_delivery_at: Optional[datetime]
    deliveries_24h_accepted: int
    deliveries_24h_failed: int


class IntegrationStatusResponse(BaseModel):
    """Response shape for `GET /api/v1/integrations/status`. Polled
    every ~30s by the Settings panel. Always returns ALL providers
    (even un-connected) so the panel can show "Not connected" tiles
    consistently."""

    providers: list[ProviderDeliveryStatus]
    dlq_open_total: int  # unreplayed + undiscarded rows across providers


__all__ = [
    "IntegrationDLQListResponse",
    "IntegrationDLQRead",
    "IntegrationProviderLiteral",
    "IntegrationRead",
    "IntegrationStatusLiteral",
    "IntegrationStatusResponse",
    "IntegrationSubscriptionCreate",
    "IntegrationSubscriptionRead",
    "IntegrationSubscriptionUpdate",
    "IntegrationUpsert",
    "ProviderDeliveryStatus",
    "SubscriptionMappingUpdate",
]
