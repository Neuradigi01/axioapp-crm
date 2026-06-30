"""Data-access layer for the custom_orders pack module.

Pure query helpers — no transactions, no audit, no pipeline-engine
orchestration. Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Custom orders (``fp_custom_orders``)
      get_order_by_id, list_orders_query,
      insert_order, delete_order_row
  * Measurements (``fp_custom_order_measurements``)
      list_measurements_for_order, insert_measurement
  * Photos (``fp_custom_order_photos``)
      list_photos_for_order, insert_photo
  * Stage history (``fp_custom_order_stages``)
      list_stage_history_for_order, insert_stage_history
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.packs.furniture.modules.custom_orders.models import (
    CustomOrder,
    CustomOrderMeasurement,
    CustomOrderPhoto,
    CustomOrderStageHistory,
)

# --- Custom orders ------------------------------------------------------


async def get_order_by_id(session: AsyncSession, order_id: uuid.UUID) -> CustomOrder | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    return (
        await session.execute(select(CustomOrder).where(CustomOrder.id == order_id))
    ).scalar_one_or_none()


async def list_orders_query(
    session: AsyncSession,
    *,
    stage: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CustomOrder], int]:
    """Filtered paginated list of custom orders, newest first."""
    filters: list[Any] = []
    if stage is not None:
        filters.append(CustomOrder.pipeline_stage == stage)
    if assigned_to_id is not None:
        filters.append(CustomOrder.assigned_to_id == assigned_to_id)
    if contact_id is not None:
        filters.append(CustomOrder.contact_id == contact_id)

    where = and_(*filters) if filters else None
    base = select(CustomOrder)
    if where is not None:
        base = base.where(where)
    base = base.order_by(CustomOrder.created_at.desc())

    total_stmt = select(func.count()).select_from(CustomOrder)
    if where is not None:
        total_stmt = total_stmt.where(where)
    total = (await session.execute(total_stmt)).scalar_one()

    offset = (page - 1) * size
    rows = (await session.execute(base.offset(offset).limit(size))).scalars().all()
    return list(rows), int(total)


def insert_order(session: AsyncSession, order: CustomOrder) -> None:
    """Register an already-constructed CustomOrder for INSERT."""
    session.add(order)


async def delete_order_row(session: AsyncSession, order: CustomOrder) -> None:
    """Mark a CustomOrder row for DELETE. Caller commits."""
    await session.delete(order)


# --- Measurements -------------------------------------------------------


async def list_measurements_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> list[CustomOrderMeasurement]:
    """All measurements for one order, earliest first (append-only
    timeline)."""
    stmt = (
        select(CustomOrderMeasurement)
        .where(CustomOrderMeasurement.order_id == order_id)
        .order_by(CustomOrderMeasurement.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def insert_measurement(session: AsyncSession, measurement: CustomOrderMeasurement) -> None:
    """Register an already-constructed CustomOrderMeasurement for
    INSERT."""
    session.add(measurement)


# --- Photos -------------------------------------------------------------


async def list_photos_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> list[CustomOrderPhoto]:
    """All photos for one order, newest first."""
    stmt = (
        select(CustomOrderPhoto)
        .where(CustomOrderPhoto.order_id == order_id)
        .order_by(CustomOrderPhoto.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


def insert_photo(session: AsyncSession, photo: CustomOrderPhoto) -> None:
    """Register an already-constructed CustomOrderPhoto for INSERT."""
    session.add(photo)


# --- Stage history ------------------------------------------------------


async def list_stage_history_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> list[CustomOrderStageHistory]:
    """Stage history for one order, earliest first — the funnel
    analytics surface this in chronological order."""
    stmt = (
        select(CustomOrderStageHistory)
        .where(CustomOrderStageHistory.order_id == order_id)
        .order_by(CustomOrderStageHistory.changed_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def insert_stage_history(session: AsyncSession, history: CustomOrderStageHistory) -> None:
    """Register an already-constructed CustomOrderStageHistory for
    INSERT."""
    session.add(history)


__all__ = [
    "delete_order_row",
    "get_order_by_id",
    "insert_measurement",
    "insert_order",
    "insert_photo",
    "insert_stage_history",
    "list_measurements_for_order",
    "list_orders_query",
    "list_photos_for_order",
    "list_stage_history_for_order",
]
