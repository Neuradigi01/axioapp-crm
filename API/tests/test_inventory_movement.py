"""Movement scenarios: receipt / dispatch / adjust + the qty_on_hand
invariant.

Each scenario sets up a warehouse + item and exercises `record_movement`
end-to-end (service level, not HTTP). The on_hand CHECK constraint is
the safety net; the service raises 400 *before* it gets there.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from src.app.packs.furniture.modules.inventory.models import MovementType
from src.app.packs.furniture.modules.inventory.schemas import (
    InventoryItemCreate,
    WarehouseCreate,
)
from src.app.packs.furniture.modules.inventory.service import (
    create_item,
    create_warehouse,
    record_movement,
)


async def _setup(test_db, seeded_admin) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a warehouse + item; returns (item_id, user_id)."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    w = await create_warehouse(
        test_db,
        org_id=org.id,
        payload=WarehouseCreate(name="Main", is_default=True),
    )
    item = await create_item(
        test_db,
        org_id=org.id,
        payload=InventoryItemCreate(
            warehouse_id=w.id,
            sku="SOF-001",
            material="Wood",
        ),
    )
    return item.id, user.id


@pytest.mark.asyncio
async def test_receipt_increments_on_hand(test_db, seeded_admin):
    item_id, user_id = await _setup(test_db, seeded_admin)

    movement = await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.receipt,
        qty=10,
    )
    assert movement.qty == 10
    # Reload item to confirm qty_on_hand.
    from sqlalchemy import select

    from src.app.packs.furniture.modules.inventory.models import InventoryItem

    item = (
        await test_db.execute(select(InventoryItem).where(InventoryItem.id == item_id))
    ).scalar_one()
    assert item.qty_on_hand == 10
    assert item.last_received_at is not None


@pytest.mark.asyncio
async def test_dispatch_decrements_on_hand(test_db, seeded_admin):
    item_id, user_id = await _setup(test_db, seeded_admin)

    await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.receipt,
        qty=10,
    )
    await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.dispatch,
        qty=3,
    )
    from sqlalchemy import select

    from src.app.packs.furniture.modules.inventory.models import InventoryItem

    item = (
        await test_db.execute(select(InventoryItem).where(InventoryItem.id == item_id))
    ).scalar_one()
    assert item.qty_on_hand == 7


@pytest.mark.asyncio
async def test_dispatch_beyond_on_hand_rejected(test_db, seeded_admin):
    item_id, user_id = await _setup(test_db, seeded_admin)
    await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.receipt,
        qty=10,
    )
    with pytest.raises(HTTPException) as exc_info:
        await record_movement(
            test_db,
            item_id=item_id,
            user_id=user_id,
            type_=MovementType.dispatch,
            qty=11,
        )
    assert exc_info.value.status_code == 400
    assert "insufficient stock" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_negative_adjust_reduces_on_hand(test_db, seeded_admin):
    """Adjust accepts a signed delta. -2 on a 10 stock yields 8."""
    item_id, user_id = await _setup(test_db, seeded_admin)
    await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.receipt,
        qty=10,
    )
    await record_movement(
        test_db,
        item_id=item_id,
        user_id=user_id,
        type_=MovementType.adjust,
        qty=-2,
    )
    from sqlalchemy import select

    from src.app.packs.furniture.modules.inventory.models import InventoryItem

    item = (
        await test_db.execute(select(InventoryItem).where(InventoryItem.id == item_id))
    ).scalar_one()
    assert item.qty_on_hand == 8


@pytest.mark.asyncio
async def test_zero_adjust_rejected(test_db, seeded_admin):
    item_id, user_id = await _setup(test_db, seeded_admin)
    with pytest.raises(HTTPException) as exc_info:
        await record_movement(
            test_db,
            item_id=item_id,
            user_id=user_id,
            type_=MovementType.adjust,
            qty=0,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_receipt_with_zero_qty_rejected(test_db, seeded_admin):
    item_id, user_id = await _setup(test_db, seeded_admin)
    with pytest.raises(HTTPException) as exc_info:
        await record_movement(
            test_db,
            item_id=item_id,
            user_id=user_id,
            type_=MovementType.receipt,
            qty=0,
        )
    assert exc_info.value.status_code == 400
