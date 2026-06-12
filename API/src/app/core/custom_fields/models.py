"""`CustomFieldDefinition` — per-org, per-entity custom field metadata.

Rule 3 of the master prompt: every entity that supports custom fields
stores its instances in a `custom_data` JSONB column on the entity row,
and the *definitions* live here. The `source` column drives behaviour:

  - ``system`` — created by core seeds; immutable `field_key`; never
    deletable; label/order/required can be edited.
  - ``pack``   — created by the pack installer (e.g. furniture); same
    immutability rules as system; label/order/hidden editable.
  - ``user``   — created by end users via the admin UI; fully editable
    and deletable.

Tenant-scoped (RLS on, ORM filter applied). Uniqueness of
`(org_id, entity_type, field_key)` is enforced by a partial-free
``UniqueConstraint`` in the migration and mirrored here for ORM-level
sanity. The render index ``(org_id, entity_type, is_hidden,
display_order)`` powers the `/render` endpoint cheaply.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class FieldType(str, enum.Enum):
    text = "text"
    number = "number"
    select = "select"
    multiselect = "multiselect"
    date = "date"
    datetime = "datetime"
    boolean = "boolean"
    phone = "phone"
    email = "email"
    currency = "currency"


class FieldSource(str, enum.Enum):
    system = "system"
    pack = "pack"
    user = "user"


# Postgres ENUM types. `create_type=True` (the default) lets
# `Base.metadata.create_all` emit `CREATE TYPE` ahead of the table, which
# the test fixture relies on. The Alembic migration uses `checkfirst=True`
# so an upgrade against a DB that already has the type is a no-op.
field_type_enum = ENUM(
    FieldType,
    name="custom_field_type",
    values_callable=lambda obj: [m.value for m in obj],
)
field_source_enum = ENUM(
    FieldSource,
    name="custom_field_source",
    values_callable=lambda obj: [m.value for m in obj],
)


class CustomFieldDefinition(Base, TenantScoped):
    __tablename__ = "tbl_custom_field_definitions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "entity_type",
            "field_key",
            name="uq_custom_fields_org_entity_key",
        ),
        Index(
            "ix_custom_fields_render",
            "org_id",
            "entity_type",
            "is_hidden",
            "display_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[FieldType] = mapped_column(field_type_enum, nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    source: Mapped[FieldSource] = mapped_column(
        field_source_enum, nullable=False, server_default=text("'user'")
    )
    pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
