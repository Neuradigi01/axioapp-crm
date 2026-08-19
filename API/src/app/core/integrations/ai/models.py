"""SQLAlchemy 2.x async models for the BYOK provider-key store.

Two tenant-scoped, RLS-on tables. The ENUMs are created by migration
``0198_ai_provider_keys``; the model declarations reference them with
``create_type=False`` so ``Base.metadata.create_all`` (used in tests
before Alembic runs) doesn't try to CREATE TYPE twice.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped

# --- ENUMs ----------------------------------------------------------------


class AiProvider(str, enum.Enum):
    """The upstream LLM provider a stored key belongs to.

    v1 supports OpenAI only; the other three values are reserved so
    future adapters (``shared/llm/anthropic.py``, ``shared/llm/google.py``,
    ``shared/llm/openrouter.py``) land without a schema change.
    """

    openai = "openai"
    anthropic = "anthropic"
    google = "google"
    openrouter = "openrouter"


ai_provider_enum = ENUM(
    AiProvider,
    name="ai_provider",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class AiProviderTestStatus(str, enum.Enum):
    """Result of the last connectivity probe against the provider."""

    untested = "untested"
    success = "success"
    failed = "failed"


ai_provider_test_status_enum = ENUM(
    AiProviderTestStatus,
    name="ai_provider_test_status",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


# --- Models ---------------------------------------------------------------


class AiProviderKey(Base, TenantScoped):
    """One row per stored provider API key.

    ``encrypted_key`` is AES-GCM ciphertext produced by
    :mod:`core.integrations.ai.crypto`. ``nonce`` (12 bytes) lives
    alongside. AAD at both encrypt + decrypt time is
    ``f"{org_id}:{id}:{key_version}"`` — an insider with SQL write
    that copies row A's ciphertext into row B's ``encrypted_key``
    column cannot decrypt it (AAD mismatch).

    ``fingerprint_sha256`` = ``sha256(api_key_plaintext.encode())``.
    The unique constraint on ``(org_id, provider, fingerprint_sha256)``
    enforces "this key is already stored" dedup within an org and
    gives security teams a JOIN target for cross-org same-key-material
    detection.
    """

    __tablename__ = "tbl_ai_provider_keys"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "provider",
            "fingerprint_sha256",
            name="uq_ai_provider_keys_org_provider_fp",
        ),
        Index(
            "ix_ai_provider_keys_org_provider_revoked",
            "org_id",
            "provider",
            "revoked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    provider: Mapped[AiProvider] = mapped_column(ai_provider_enum, nullable=False)
    label: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        server_default=sql_text("'Default'"),
    )
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("1"),
    )
    fingerprint_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    test_status: Mapped[AiProviderTestStatus] = mapped_column(
        ai_provider_test_status_enum,
        nullable=False,
        server_default=sql_text("'untested'"),
    )
    test_last_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    test_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class OrgAiCostBudget(Base, TenantScoped):
    """One row per org (UNIQUE). Daily/monthly USD caps + running
    spent counters. The chat runtime (Step 9) reads this before every
    LLM call via ``service.charge_budget(..., dry_run=True)`` and
    short-circuits with the fallback message when a cap would be
    exceeded.

    ``day_bucket`` (DATE) and ``month_bucket`` (text ``YYYY-MM``) let
    the service detect a rollover in application code (choice of
    timezone lives there, not in the DB).
    """

    __tablename__ = "tbl_org_ai_cost_budget"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # Redeclare with UNIQUE — TenantScoped's org_id has index=True but
    # not unique; migration sets the UNIQUE constraint separately.
    daily_cap_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default=sql_text("10.00"),
    )
    monthly_cap_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default=sql_text("200.00"),
    )
    spent_today_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default=sql_text("0"),
    )
    spent_month_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default=sql_text("0"),
    )
    day_bucket: Mapped[date | None] = mapped_column(Date, nullable=True)
    month_bucket: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


__all__ = [
    "AiProvider",
    "AiProviderKey",
    "AiProviderTestStatus",
    "OrgAiCostBudget",
    "ai_provider_enum",
    "ai_provider_test_status_enum",
]
