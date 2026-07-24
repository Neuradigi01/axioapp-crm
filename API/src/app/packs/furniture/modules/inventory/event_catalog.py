"""Furniture pack — inventory module event catalog
(``tasks/automation-conditions/`` Step 7 skeleton).

Skeleton wiring: registers ONE representative event
(``inventory.item_low_stock``) + TWO placeholder enum resolvers
(``fp_warehouses``, ``fp_item_categories``) to prove the
core→pack discovery walker + auto-tagging + tenant filter all
work end-to-end.

The full furniture-pack event coverage (inventory movements, custom-
order status transitions, field-ops appointments, etc.) lands with
the dedicated furniture-pack workstream (rule 7 keeps the current
Core CRM phase vertical-agnostic — this file is the minimum needed
to prove the framework, not the vertical's real feature surface).

Import-side effects: the module-registry walker imports this file
during app startup with the pack ContextVar set to ``"furniture"``.
Every ``register_event`` / ``register_field_resolver`` call inside
auto-tags with ``pack_id="furniture"`` so the ``/event-types``
endpoint filters correctly by ``org.template_id``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import (
    CatalogEntry,
    EnumOption,
    FieldSpec,
    FieldType,
    register_event,
    register_field_resolver,
)

# --- resolvers ------------------------------------------------------


async def _resolve_fp_warehouses(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Placeholder resolver for the furniture pack's warehouses.

    Real implementation reads ``tbl_fp_warehouses`` for the caller
    org once the furniture-pack workstream adds it. For now returns
    a short static demo list so the skeleton event's Value dropdown
    shows something rather than an empty list — the framework wiring
    is what step-7 proves; the vertical's real data model is
    someone else's concern.
    """
    return [
        EnumOption(value="bengaluru", label="Bengaluru"),
        EnumOption(value="mumbai", label="Mumbai"),
        EnumOption(value="delhi", label="Delhi"),
    ]


async def _resolve_fp_item_categories(
    _session: AsyncSession, _org_id: uuid.UUID
) -> list[EnumOption]:
    """Placeholder resolver for furniture item categories. Same note
    as :func:`_resolve_fp_warehouses`."""
    return [
        EnumOption(value="seating", label="Seating"),
        EnumOption(value="tables", label="Tables"),
        EnumOption(value="beds", label="Beds"),
        EnumOption(value="storage", label="Storage"),
    ]


# --- registration ---------------------------------------------------

register_field_resolver("fp_warehouses", _resolve_fp_warehouses)
register_field_resolver("fp_item_categories", _resolve_fp_item_categories)

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "item_id": "00000000-0000-0000-0000-000000000000",
    "item": {
        "id": "00000000-0000-0000-0000-000000000000",
        "sku": "SOFA-LR-001",
        "warehouse": "bengaluru",
        "category": "seating",
        "stock_level": 3,
    },
    "org": {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "Demo Workspace",
        "slug": "demo-workspace",
    },
}


register_event(
    CatalogEntry(
        event_type="inventory.item_low_stock",
        label="Inventory item low stock",
        description=(
            "Fires when a furniture item's stock level drops below "
            "its configured reorder threshold. Only visible to orgs "
            "on the furniture pack."
        ),
        sample_payload=_SAMPLE_PAYLOAD,
        condition_fields=(
            FieldSpec(
                path="item.sku",
                label="SKU",
                type=FieldType.text,
                group="Item",
            ),
            FieldSpec(
                path="item.warehouse",
                label="Warehouse",
                type=FieldType.enum,
                group="Item",
                enum_resolver="fp_warehouses",
            ),
            FieldSpec(
                path="item.category",
                label="Category",
                type=FieldType.enum,
                group="Item",
                enum_resolver="fp_item_categories",
            ),
            FieldSpec(
                path="item.stock_level",
                label="Stock level",
                type=FieldType.number,
                group="Item",
            ),
        ),
    )
)
