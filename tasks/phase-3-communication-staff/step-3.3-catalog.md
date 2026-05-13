# Step 3.3 — Catalog (basic): backend + frontend

**Goal:** Bare-minimum core catalog so Walk-ins/Leads can reference a "product interest." Furniture pack will extend with rich Inventory in Phase 4.
**Phase:** 3
**Depends on:** 1.5
**Status:** COMPLETED

## Scope
**In-scope:**
- Model `CatalogItem` (TenantScoped): id, org_id, sku, name, category, price, currency (default INR), custom_data JSONB, is_active, created_at, updated_at.
- Migration + RLS + indexes (`org_id, sku unique`, `org_id, category`).
- Endpoints: `/api/v1/catalog` CRUD + `GET /catalog?q=&category=`.
- Permissions: `catalog.read`, `catalog.write`.
- Frontend: `app/src/app/features/user/core/catalog/` page — simple table + add-item modal.
- Module descriptor (sidebar: "Catalog").

**Out of scope:**
- Multi-warehouse / stock movements / images / reorder logic — Phase 4 (`fp_inventory_items` extends this).

## Files to touch
- `api/src/app/core/catalog/*` (created)
- `api/alembic/versions/0015_catalog_items.py` (created)
- `app/src/app/features/user/core/catalog/*` (created)

## Plan
1. Backend model + migration + endpoints.
2. Frontend list + add modal with simple Tailwind form.
3. Item picker component reusable from Walk-ins / Leads (autocomplete by SKU/name) — added under `core/shared/item-picker/`.

## Verification checklist
**Backend:**
- `POST /catalog` body=`{sku:"SOF001",name:"3-seater Sofa",price:25000,category:"Sofa"}` → 201.
- `GET /catalog?q=sofa` → returns it.
**Frontend:**
- visit `/catalog` → table + add-item.

## Self-check (10 rules)
- [ ] org_id + RLS; SKU unique per org.

## Stop & report
Await "proceed" before Step 3.4.
