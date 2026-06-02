"""Service layer for the furniture-pack custom-orders module.

Four concerns:

1. CRUD over `fp_custom_orders` — paginated list, get/create/update/delete.
2. `move_stage` — reuses the core pipelines engine (`pipelines.move_card`)
   so the transition validates against the seeded `custom_orders`
   pipeline and writes a `status_change` activity on the contact
   timeline automatically. We also append a `CustomOrderStageHistory`
   row for funnel analytics that's specific to this module.
3. Measurements — append-only per order.
4. Photos — uploaded via `StorageBackend`; URL persisted here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.shared.audit import log_entity_change
from src.app.core.pipelines.service import move_card as pipeline_move_card
from src.app.packs.furniture.modules.custom_orders.models import (
    CustomOrder,
    CustomOrderMeasurement,
    CustomOrderPhoto,
    CustomOrderStageHistory,
)
from src.app.packs.furniture.modules.custom_orders.schemas import (
    CustomOrderCreate,
    CustomOrderUpdate,
    MeasurementCreate,
)
from src.app.shared.db.queries import get_or_404
from src.app.shared.storage import get_storage


_PIPELINE_KEY = "custom_orders"
_CARD_TABLE = "fp_custom_orders"
_INITIAL_STAGE = "measurement_scheduled"


# --- reads ----------------------------------------------------------------


async def list_orders(
    session: AsyncSession,
    *,
    stage: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    contact_id: Optional[uuid.UUID] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CustomOrder], int]:
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
    rows = (
        (await session.execute(base.offset(offset).limit(size)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_order(
    session: AsyncSession, order_id: uuid.UUID
) -> CustomOrder:
    return await get_or_404(session, CustomOrder, order_id, entity="custom order")


# --- writes ---------------------------------------------------------------


async def create_order(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CustomOrderCreate,
) -> CustomOrder:
    order = CustomOrder(
        org_id=org_id,
        contact_id=payload.contact_id,
        lead_id=payload.lead_id,
        title=payload.title,
        requirement=payload.requirement,
        materials=payload.materials,
        color=payload.color,
        finish=payload.finish,
        pipeline_stage=_INITIAL_STAGE,
        assigned_to_id=payload.assigned_to_id,
        expected_delivery_date=payload.expected_delivery_date,
        total_amount=payload.total_amount,
        advance_paid=payload.advance_paid,
        custom_data=payload.custom_data,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    # First stage entry — records the implicit "created at
    # measurement_scheduled" transition.
    session.add(
        CustomOrderStageHistory(
            org_id=org_id,
            order_id=order.id,
            from_stage=None,
            to_stage=_INITIAL_STAGE,
            user_id=user_id,
            notes="order created",
        )
    )
    await session.commit()

    await log_entity_change(
        action="custom_orders.created",
        entity_type="custom_order",
        entity_id=order.id,
        after={"title": order.title, "stage": order.pipeline_stage},
    )
    return order


async def update_order(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    payload: CustomOrderUpdate,
) -> CustomOrder:
    order = await get_order(session, order_id)
    changed = False
    for field in (
        "contact_id", "lead_id", "title", "requirement", "materials",
        "color", "finish", "assigned_to_id", "expected_delivery_date",
        "total_amount", "advance_paid", "custom_data",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(order, field, value)
            changed = True
    if changed:
        await session.commit()
        await session.refresh(order)
    return order


async def delete_order(
    session: AsyncSession, *, order_id: uuid.UUID
) -> None:
    order = await get_order(session, order_id)
    await session.delete(order)
    await session.commit()


# --- stage transition ----------------------------------------------------


async def move_stage(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    to_stage: str,
    notes: Optional[str] = None,
) -> CustomOrder:
    """Reuse the core pipeline engine for the transition + the per-order
    stage history append.

    `pipeline_move_card` validates the stage key against the seeded
    pipeline, UPDATEs `fp_custom_orders.pipeline_stage`, writes a
    `status_change` activity, and an audit row — all in the same
    transaction. We then append a row to `fp_custom_order_stages`
    for funnel analytics specific to this module.
    """
    order = await get_order(session, order_id)
    from_stage = order.pipeline_stage

    if from_stage == to_stage:
        return order

    await pipeline_move_card(
        session,
        pipeline_key=_PIPELINE_KEY,
        card_table=_CARD_TABLE,
        card_id=order.id,
        to_stage_key=to_stage,
        user_id=user_id,
    )

    # `move_card` issued raw SQL UPDATE then committed; the ORM-level
    # `order` is now stale. Re-fetch so subsequent reads see the new
    # stage, then append the history row.
    await session.refresh(order)
    session.add(
        CustomOrderStageHistory(
            org_id=order.org_id,
            order_id=order.id,
            from_stage=from_stage,
            to_stage=to_stage,
            user_id=user_id,
            notes=notes,
        )
    )
    await session.commit()
    return order


# --- measurements --------------------------------------------------------


async def list_measurements(
    session: AsyncSession, *, order_id: uuid.UUID
) -> list[CustomOrderMeasurement]:
    stmt = (
        select(CustomOrderMeasurement)
        .where(CustomOrderMeasurement.order_id == order_id)
        .order_by(CustomOrderMeasurement.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def add_measurement(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    payload: MeasurementCreate,
) -> CustomOrderMeasurement:
    order = await get_order(session, order_id)
    m = CustomOrderMeasurement(
        org_id=order.org_id,
        order_id=order.id,
        item_label=payload.item_label,
        length_cm=payload.length_cm,
        width_cm=payload.width_cm,
        height_cm=payload.height_cm,
        notes=payload.notes,
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    return m


# --- photos --------------------------------------------------------------


async def list_photos(
    session: AsyncSession, *, order_id: uuid.UUID
) -> list[CustomOrderPhoto]:
    stmt = (
        select(CustomOrderPhoto)
        .where(CustomOrderPhoto.order_id == order_id)
        .order_by(CustomOrderPhoto.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def add_photo(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    data: bytes,
    content_type: str,
    file_extension: str,
    caption: Optional[str] = None,
) -> CustomOrderPhoto:
    """Persist the binary via `StorageBackend`, then write the row."""
    order = await get_order(session, order_id)
    photo_id = uuid.uuid4()
    storage_path = (
        f"{order.org_id}/custom_orders/{order.id}/photo-{photo_id}.{file_extension}"
    )
    ref = get_storage().put(storage_path, data, content_type=content_type)

    photo = CustomOrderPhoto(
        id=photo_id,
        org_id=order.org_id,
        order_id=order.id,
        url=ref.url,
        caption=caption,
        taken_at=datetime.now(timezone.utc),
    )
    session.add(photo)
    await session.commit()
    await session.refresh(photo)
    return photo


# --- stage history reads -------------------------------------------------


async def list_stage_history(
    session: AsyncSession, *, order_id: uuid.UUID
) -> list[CustomOrderStageHistory]:
    stmt = (
        select(CustomOrderStageHistory)
        .where(CustomOrderStageHistory.order_id == order_id)
        .order_by(CustomOrderStageHistory.changed_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "add_measurement",
    "add_photo",
    "create_order",
    "delete_order",
    "get_order",
    "list_measurements",
    "list_orders",
    "list_photos",
    "list_stage_history",
    "move_stage",
    "update_order",
]
