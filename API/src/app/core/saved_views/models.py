"""SavedView model — per-user named bundle of list-page settings.

A "saved view" is a JSON blob (`config`) plus a name and a sharing
flag. The intended consumer is the leads / contacts / walk-ins list
pages: the user composes a filter + sort + columns, saves it, and gets
a one-click "re-apply" entry in a toolbar dropdown.

The ``entity`` discriminator scopes a view to one list page. Step 7
populates only ``'leads'`` — adding ``'contacts'`` etc. just means
emitting that string from the new list page; no schema change.

Tenant isolation:
  - ``org_id`` + standard RLS keep rows out of cross-tenant queries.
  - Within an org, ``owner_user_id`` and ``shared`` decide who sees
    the row. The service layer does the OR/AND of those two; RLS does
    not (the codebase doesn't expose the current user id to Postgres
    session variables, so an in-policy `current_user_id` predicate
    has nothing to read).

Owner pointer:
  - ``owner_user_id`` is a UUID matching ``User.legacy_uuid``. No FK
    constraint — per migration 0062 the codebase dropped all FKs to
    the user tables. If the owner is deactivated the row stays put;
    the view becomes inaccessible because login flow gates the FE
    fetch by ``user.legacy_uuid``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class SavedView(Base, TenantScoped):
    __tablename__ = "saved_views"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    # ``leads`` for now; reusable for ``contacts``, ``walk_ins``, etc.
    # Kept as plain VARCHAR so adding a new entity is one FE change,
    # not a schema migration.
    entity: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # JSONB so we can index/probe individual keys later if needed (e.g.
    # "which views reference custom field X"). Today the FE consumes
    # the blob whole.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
