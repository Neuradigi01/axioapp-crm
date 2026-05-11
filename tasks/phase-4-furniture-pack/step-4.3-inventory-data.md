# Step 4.3 — Furniture: Inventory & Warehouse — backend (data)

**Goal:** `fp_warehouses`, `fp_inventory_items`, `fp_inventory_movements`, `fp_stock_alerts` tables. Models, schemas, repositories, CRUD, reorder logic. **First Layer 2 (pack) module touching the database.**
**Phase:** 4
**Depends on:** 4.2, 3.3 (catalog)
**Status:** Pending

## Scope
**In-scope:**
- Pack module path: `api/src/app/packs/furniture/modules/inventory/`.
- Models (TenantScoped, all `fp_*` tables):
  - `Warehouse` (`fp_warehouses`): id, org_id, name, address, contact_phone, is_default.
  - `InventoryItem` (`fp_inventory_items`): id, org_id, catalog_item_id (FK→`catalog_items`), warehouse_id, sku, material, color, finish, dimensions JSONB, qty_on_hand, qty_reserved, reorder_level, last_received_at, custom_data JSONB, is_best_seller (bool — manually toggled or computed), is_active.
  - `InventoryMovement` (`fp_inventory_movements`): id, org_id, item_id, type (receipt/dispatch/adjust/transfer), qty, reference_type, reference_id, notes, user_id, created_at.
  - `StockAlert` (`fp_inventory_alerts`): id, org_id, item_id, severity (low/out), priority (high/med/low), suggested_reorder_qty, status (open/ordered/closed), created_at, closed_at.
- Migration `0023_fp_inventory.py` + RLS on all four tables.
- Service:
  - `record_movement(item_id, type, qty, ref, user_id)` — atomically updates `qty_on_hand` (validates non-negative), inserts movement, computes alerts.
  - `recompute_alerts(item_id)` — opens/closes alerts based on `qty_on_hand` vs `reorder_level`.
- Endpoints (under `/api/v1/inventory/`):
  - `/warehouses` CRUD.
  - `/items` CRUD + filters (warehouse, category-via-catalog-join, search).
  - `/items/{id}/movements` — list, `POST` to record.
  - `/alerts` list (filters: severity, status).
- Permissions: `inventory.read`, `inventory.write`, `inventory.dispatch`, `inventory.transfer`.

**Out of scope:**
- Module registration / sidebar — 4.4.
- Frontend — 4.5/4.6/4.7.

## Files to touch
- `api/src/app/packs/furniture/modules/inventory/{__init__,models,schemas,service,router}.py` (created)
- `api/alembic/versions/0023_fp_inventory.py` (created)

## Plan
1. Models + migration. `qty_on_hand` constraint ≥ 0; `qty_reserved` ≤ `qty_on_hand`.
2. Reorder logic: trigger `recompute_alerts` whenever a movement updates qty.
3. Service ensures movement + qty change are in the same transaction.

## Tests to add
- `tests/test_inventory_movement.py` — receipt + dispatch + adjust scenarios.
- `tests/test_inventory_alerts.py` — alert created when qty drops below reorder_level; closed when restocked.

## Verification checklist
**Backend:**
- create warehouse + item → `qty_on_hand=0`.
- record receipt qty=10 → `qty_on_hand=10`.
- record dispatch qty=11 → 400.
- set reorder_level=5, dispatch 7 → alert opened.

## Self-check (10 rules)
- [ ] org_id + RLS on all four tables.
- [ ] `src.app.packs.furniture` may import `src.app.core` (allowed); `src.app.core` does NOT import `src.app.packs.furniture`.

## Stop & report
Await "proceed" before Step 4.4.
