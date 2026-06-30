"""Stock alerts open / close in lockstep with qty_on_hand vs reorder_level."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.app.packs.furniture.modules.inventory.models import (
    AlertSeverity,
    AlertStatus,
    MovementType,
    StockAlert,
)
from src.app.packs.furniture.modules.inventory.schemas import (
    InventoryItemCreate,
    InventoryItemUpdate,
    WarehouseCreate,
)
from src.app.packs.furniture.modules.inventory.service import (
    create_item,
    create_warehouse,
    record_movement,
    update_item,
)


async def _make_item(test_db, org_id: uuid.UUID, *, reorder_level: int):
    w = await create_warehouse(
        test_db,
        org_id=org_id,
        payload=WarehouseCreate(name="Main"),
    )
    return await create_item(
        test_db,
        org_id=org_id,
        payload=InventoryItemCreate(
            warehouse_id=w.id,
            sku="X-001",
            reorder_level=reorder_level,
        ),
    )


async def _open_alert(test_db, item_id: uuid.UUID):
    return (
        await test_db.execute(
            select(StockAlert)
            .where(StockAlert.item_id == item_id)
            .where(StockAlert.status == AlertStatus.open)
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_alert_opened_when_qty_zero_and_reorder_positive(test_db, seeded_admin):
    org = seeded_admin["org"]
    item = await _make_item(test_db, org.id, reorder_level=5)
    # Fresh item: qty_on_hand=0, reorder_level=5 → out-of-stock alert
    alert = await _open_alert(test_db, item.id)
    assert alert is not None
    assert alert.severity == AlertSeverity.out


@pytest.mark.asyncio
async def test_alert_closes_when_restocked(test_db, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    item = await _make_item(test_db, org.id, reorder_level=5)
    assert (await _open_alert(test_db, item.id)) is not None

    # Receipt 10 → qty_on_hand=10, above reorder_level=5 → alert closes
    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.receipt,
        qty=10,
    )
    assert (await _open_alert(test_db, item.id)) is None


@pytest.mark.asyncio
async def test_alert_low_then_out_when_dispatched_below_reorder(test_db, seeded_admin):
    """Dispatch 7 from on_hand=10, reorder_level=5 → on_hand=3 → low.
    Dispatch 3 more → on_hand=0 → out (severity upgraded on same alert).
    """
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    item = await _make_item(test_db, org.id, reorder_level=5)
    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.receipt,
        qty=10,
    )
    # No alert at on_hand=10 > reorder=5.
    assert (await _open_alert(test_db, item.id)) is None

    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.dispatch,
        qty=7,
    )
    alert = await _open_alert(test_db, item.id)
    assert alert is not None
    assert alert.severity == AlertSeverity.low

    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.dispatch,
        qty=3,
    )
    alert = await _open_alert(test_db, item.id)
    assert alert is not None
    assert alert.severity == AlertSeverity.out


@pytest.mark.asyncio
async def test_no_alert_when_reorder_level_zero(test_db, seeded_admin):
    """`reorder_level=0` opts the item out of alerting."""
    org = seeded_admin["org"]
    item = await _make_item(test_db, org.id, reorder_level=0)
    assert (await _open_alert(test_db, item.id)) is None


@pytest.mark.asyncio
async def test_raising_reorder_level_opens_alert(test_db, seeded_admin):
    """If on_hand=3 and reorder_level was 0, raising to 5 should open."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    item = await _make_item(test_db, org.id, reorder_level=0)
    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.receipt,
        qty=3,
    )
    assert (await _open_alert(test_db, item.id)) is None

    await update_item(
        test_db,
        item_id=item.id,
        payload=InventoryItemUpdate(reorder_level=5),
    )
    alert = await _open_alert(test_db, item.id)
    assert alert is not None
    assert alert.severity == AlertSeverity.low


@pytest.mark.asyncio
async def test_suggested_reorder_qty_doubled_minus_on_hand(test_db, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    item = await _make_item(test_db, org.id, reorder_level=10)
    await record_movement(
        test_db,
        item_id=item.id,
        user_id=user.id,
        type_=MovementType.receipt,
        qty=3,
    )
    alert = await _open_alert(test_db, item.id)
    # suggested = max(10*2 - 3, 0) = 17
    assert alert is not None
    assert alert.suggested_reorder_qty == 17
