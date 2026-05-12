"""Pipelines engine — generic kanban primitive used by Leads, Custom Orders, …

Two tables:

- `pipelines`        — one named pipeline per (org_id, key). The `key`
                       is the stable identifier other tables reference
                       (e.g. a leads row's `pipeline_stage` text column
                       stores the stage's `key`, not its UUID, because
                       stage UUIDs change on re-seed but keys do not).
- `pipeline_stages`  — ordered columns of a pipeline. `key`, `is_won`,
                       `is_lost` are immutable; `name`, `color`,
                       `display_order` are editable (rule: see
                       `service.update_stage`).

Tenant-scoped (RLS on, ORM filter applied). The pack installer (Phase
4) is the canonical creator of rows; the HTTP layer here exposes
read-only + label/color/order updates, never `key` changes.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class Pipeline(Base, TenantScoped):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_pipelines_org_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    stages: Mapped[list["PipelineStage"]] = relationship(
        "PipelineStage",
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="PipelineStage.display_order",
    )


class PipelineStage(Base, TenantScoped):
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id",
            "key",
            name="uq_pipeline_stages_pipeline_key",
        ),
        UniqueConstraint(
            "pipeline_id",
            "display_order",
            name="uq_pipeline_stages_pipeline_order",
            # NOTE: The migration declares this constraint INITIALLY
            # DEFERRED so a single-stage PATCH that does a "trade
            # places" swap can violate uniqueness mid-transaction and
            # still commit cleanly. The mirror here is for ORM-level
            # awareness only — Postgres is the authority.
        ),
        Index(
            "ix_pipeline_stages_order",
            "pipeline_id",
            "display_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_won: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_lost: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    pipeline: Mapped[Pipeline] = relationship(
        "Pipeline", back_populates="stages"
    )
