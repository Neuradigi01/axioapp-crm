"""ORM for the WhatsApp Web (unofficial / Baileys) sidecar correlation.

One ``Integration`` row per (org, provider=whatsapp_web) carries the
high-level connection state and timestamps just like every other
provider. This sidecar table carries the bits the generic integrations
shape doesn't fit:

  - ``sidecar_session_id`` — the UUID FastAPI generates and passes to
    the Node sidecar on connect. The sidecar uses it as the key for
    its Baileys session map AND as the path segment for every
    /sessions/{id} call back to it.
  - ``status`` — fine-grained Baileys lifecycle state mirrored from the
    sidecar's ``SessionStatus`` (plus ``pending`` for the brief window
    before the sidecar acks). The parent ``Integration.status`` stays
    on the coarse ``connected | disconnected`` axis.
  - ``phone_number`` — captured from the sidecar's ``connection.opened``
    event. The parent ``Integration.account_label`` mirrors this for
    UI surfaces that already render that field.
  - ``last_event_at`` — debug aid for the operator when a session looks
    stuck. Updated on every inbound sidecar event.

UNIQUE on ``integration_id`` enforces the one-Web-session-per-org rule
for v1 (multi-number per WABA is the Cloud-track Step 27a equivalent;
multi-number Web is a future track).

Tenant-scoped via the ``TenantScoped`` mixin + RLS policy from
``alembic/versions/0141_whatsapp_web.py``. The ORM tenant filter
auto-applies to every SELECT.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class WhatsAppWebSession(Base, TenantScoped):
    """One row per WhatsApp Web sidecar session.

    Lifecycle::

        pending → pairing → connected
                          ↘ reconnecting → connected (loop on transient close)
                          ↘ logged_out (terminal — needs a new pairing)
                          ↘ error (terminal — last_error explains)

    ``disconnected`` is what the FastAPI service flips to when the
    operator clicks Disconnect; it's distinct from ``logged_out`` which
    is what the sidecar reports when WhatsApp itself drops the session.
    """

    __tablename__ = "tbl_whatsapp_web_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    sidecar_session_id: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    phone_number: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    last_event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"WhatsAppWebSession(id={self.id!s}, "
            f"integration_id={self.integration_id!s}, "
            f"status={self.status!r}, "
            f"phone_number={self.phone_number!r})"
        )


__all__ = ["WhatsAppWebSession"]
