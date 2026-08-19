"""Pydantic v2 request + response shapes.

Write schemas set ``extra='forbid'`` and explicitly whitelist inputs —
any attempt to POST ``{"org_id": "<victim>", "id": "<forged>",
"fingerprint_sha256": "...", "encrypted_key": "..."}`` is rejected
at the schema layer with 422 before the service ever sees it
(mass-assignment defence, Attacker review H2).

Read schemas NEVER return ``encrypted_key`` / ``fingerprint_sha256``
/ ``nonce`` — only the masked ``last4`` is safe to send back. Even
the operator who just created the key sees only the last-4 after
save; editing an existing key is re-entry, not display.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.integrations.ai.models import AiProvider, AiProviderTestStatus

# --- Provider keys -------------------------------------------------------


class AiProviderKeyCreate(BaseModel):
    """Operator POSTs this to add a new provider key.

    The **`api_key`** field carries the plaintext key — it is
    encrypted by the service before any DB write and NEVER stored
    plaintext, NEVER logged, and NEVER returned in any response.
    """

    model_config = ConfigDict(extra="forbid")

    provider: AiProvider = Field(..., description="Upstream LLM provider.")
    label: str = Field(
        default="Default",
        min_length=1,
        max_length=120,
        description="Human-readable label — 'Default', 'Marketing', etc.",
    )
    api_key: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="The plaintext API key. Encrypted before storage.",
    )


class AiProviderKeyRead(BaseModel):
    """Response shape — safe to send to the operator UI.

    NEVER includes ``encrypted_key``, ``nonce``, or
    ``fingerprint_sha256``. Only the masked ``last4`` renders in the
    UI (e.g. ``sk-…AB12``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: AiProvider
    label: str
    last4: str
    test_status: AiProviderTestStatus
    test_last_at: datetime | None
    test_last_error: str | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiProviderKeyReassign(BaseModel):
    """POST body for the reassign flow — swap all assistant references
    from one key to another before deleting the first. Both keys must
    belong to the caller's org (cross-org validated in the service).
    """

    model_config = ConfigDict(extra="forbid")

    from_key_id: uuid.UUID
    to_key_id: uuid.UUID


class AiProviderKeyDeleteBlocked(BaseModel):
    """Response body when DELETE is refused because assistants
    reference the key. The UI opens a Reassign modal and lists the
    referencing rows.
    """

    reason: str = "referenced_by_assistants"
    reference_count: int
    key_id: uuid.UUID


class AiProviderKeyDuplicate(BaseModel):
    """Response body on 409 when the same key material already exists
    for this org+provider. UI shows an info banner with the existing
    row's masked last-4."""

    reason: str = "key_already_stored"
    existing_key_id: uuid.UUID
    last4: str


# --- Cost budget ---------------------------------------------------------


class OrgAiCostBudgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    daily_cap_usd: Decimal
    monthly_cap_usd: Decimal
    spent_today_usd: Decimal
    spent_month_usd: Decimal
    day_bucket: date | None
    month_bucket: str | None


class OrgAiCostBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_cap_usd: Decimal | None = Field(default=None, ge=0, le=Decimal("9999.9999"))
    monthly_cap_usd: Decimal | None = Field(default=None, ge=0, le=Decimal("999999.9999"))


__all__ = [
    "AiProviderKeyCreate",
    "AiProviderKeyDeleteBlocked",
    "AiProviderKeyDuplicate",
    "AiProviderKeyReassign",
    "AiProviderKeyRead",
    "OrgAiCostBudgetRead",
    "OrgAiCostBudgetUpdate",
]
