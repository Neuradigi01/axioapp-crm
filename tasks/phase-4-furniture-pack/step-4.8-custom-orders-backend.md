# Step 4.8 — Furniture: Custom Orders — backend

**Goal:** `fp_custom_orders`, `fp_custom_order_measurements`, `fp_custom_order_photos`, `fp_custom_order_stages` tables. Reuse pipeline engine for production stages. File upload for site photos.
**Phase:** 4
**Depends on:** 2.9, 2.4, 4.3, 4.7 (storage)
**Status:** COMPLETED
## Scope
**In-scope:**
- Models (TenantScoped):
  - `CustomOrder` (`fp_custom_orders`): id, org_id, contact_id, lead_id (nullable), title, requirement, materials JSONB, color, finish, pipeline_stage (text — re
  ferences `pipelines.custom_orders` stages), assigned_to_id, expected_delivery_date, total_amount, advance_paid, custom_data JSONB, created_at, updated_at.
  - `CustomOrderMeasurement` (`fp_custom_order_measurements`): id, org_id, order_id, item_label, length_cm, width_cm, height_cm, notes.
  - `CustomOrderPhoto` (`fp_custom_order_photos`): id, org_id, order_id, url, caption, taken_at.
  - `CustomOrderStageHistory` (`fp_custom_order_stages`): id, org_id, order_id, from_stage, to_stage, user_id, notes, changed_at. (Used for analytics; movement also writes to core `activities`.)
- Migration `0024_fp_custom_orders.py` + RLS.
- Endpoints `/api/v1/custom-orders`:
  - CRUD.
  - `POST /custom-orders/{id}/measurements`
  - `POST /custom-orders/{id}/photos` (multipart)
  - `POST /custom-orders/{id}/move-stage` — uses `pipelines.move_card`.
- Permissions: `custom_orders.read`, `custom_orders.write`, `custom_orders.move`.
- Module descriptor (sidebar entry, layer=`pack`).

## Files to touch
- `api/src/app/packs/furniture/modules/custom_orders/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0024_fp_custom_orders.py` (created)

## Plan
1. Models + migration.
2. Service: stage move uses pipeline engine; logs activity.
3. Photo upload uses StorageBackend; stores under `/storage/{org}/custom_orders/{order_id}/photo-{uuid}.jpg`.

## Tests to add
- `tests/test_custom_orders_crud.py`
- `tests/test_custom_orders_stage.py`

## Verification checklist
**Backend:**
- `POST /custom-orders` → 201 in stage `measurement_scheduled`.
- move stage → audit + activity rows.
- upload photo → URL persisted.

## Self-check (10 rules)
- [ ] org_id + RLS on all tables.
- [ ] Pipeline engine reused (no duplication).

## Stop & report
Await "proceed" before Step 4.9.
