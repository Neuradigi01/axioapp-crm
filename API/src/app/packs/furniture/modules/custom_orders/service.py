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
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.pipelines.service import move_card as pipeline_move_card
from src.app.packs.furniture.modules.custom_orders import data_access as _da
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
from src.app.shared.audit import log_entity_change
from src.app.shared.db.queries import ensure_found
from src.app.shared.storage import get_storage

_PIPELINE_KEY = "custom_orders"
_CARD_TABLE = "fp_custom_orders"
_INITIAL_STAGE = "measurement_scheduled"


# --- reads ----------------------------------------------------------------


async def list_orders(
    session: AsyncSession,
    *,
    stage: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CustomOrder], int]:
    return await _da.list_orders_query(
        session,
        stage=stage,
        assigned_to_id=assigned_to_id,
        contact_id=contact_id,
        page=page,
        size=size,
    )


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> CustomOrder:
    return ensure_found(await _da.get_order_by_id(session, order_id), entity="custom order")


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
    _da.insert_order(session, order)
    await session.commit()
    await session.refresh(order)

    # First stage entry — records the implicit "created at
    # measurement_scheduled" transition.
    _da.insert_stage_history(
        session,
        CustomOrderStageHistory(
            org_id=org_id,
            order_id=order.id,
            from_stage=None,
            to_stage=_INITIAL_STAGE,
            user_id=user_id,
            notes="order created",
        ),
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
        "contact_id",
        "lead_id",
        "title",
        "requirement",
        "materials",
        "color",
        "finish",
        "assigned_to_id",
        "expected_delivery_date",
        "total_amount",
        "advance_paid",
        "custom_data",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(order, field, value)
            changed = True
    if changed:
        await session.commit()
        await session.refresh(order)
    return order


async def delete_order(session: AsyncSession, *, order_id: uuid.UUID) -> None:
    order = await get_order(session, order_id)
    await _da.delete_order_row(session, order)
    await session.commit()


# --- stage transition ----------------------------------------------------


async def move_stage(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    to_stage: str,
    notes: str | None = None,
) -> CustomOrder:
    """Reuse the core pipeline engine for the transition + the per-order
    stage history append."""
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
    _da.insert_stage_history(
        session,
        CustomOrderStageHistory(
            org_id=order.org_id,
            order_id=order.id,
            from_stage=from_stage,
            to_stage=to_stage,
            user_id=user_id,
            notes=notes,
        ),
    )
    await session.commit()
    return order


# --- measurements --------------------------------------------------------


async def list_measurements(
    session: AsyncSession, *, order_id: uuid.UUID
) -> list[CustomOrderMeasurement]:
    return await _da.list_measurements_for_order(session, order_id)


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
    _da.insert_measurement(session, m)
    await session.commit()
    await session.refresh(m)
    return m


# --- photos --------------------------------------------------------------


async def list_photos(session: AsyncSession, *, order_id: uuid.UUID) -> list[CustomOrderPhoto]:
    return await _da.list_photos_for_order(session, order_id)


async def add_photo(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    data: bytes,
    content_type: str,
    file_extension: str,
    caption: str | None = None,
) -> CustomOrderPhoto:
    """Persist the binary via `StorageBackend`, then write the row."""
    order = await get_order(session, order_id)
    photo_id = uuid.uuid4()
    storage_path = f"{order.org_id}/custom_orders/{order.id}/photo-{photo_id}.{file_extension}"
    ref = await get_storage().put(storage_path, data, content_type=content_type)

    photo = CustomOrderPhoto(
        id=photo_id,
        org_id=order.org_id,
        order_id=order.id,
        url=ref.url,
        caption=caption,
        taken_at=datetime.now(UTC),
    )
    _da.insert_photo(session, photo)
    await session.commit()
    await session.refresh(photo)
    return photo


# --- stage history reads -------------------------------------------------


async def list_stage_history(
    session: AsyncSession, *, order_id: uuid.UUID
) -> list[CustomOrderStageHistory]:
    return await _da.list_stage_history_for_order(session, order_id)


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
