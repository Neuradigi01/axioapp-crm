# Step 4.7 — Inventory — Add Product modal

**Goal:** Add New Product modal matching the screenshot — SKU, category, material, color, warehouse, reorder level, description.
**Phase:** 4
**Depends on:** 4.5
**Status:** Pending

## Scope
**In-scope:**
- `add-product-modal.component.ts/.html` under inventory.
- Creates a `catalog_items` row (core) + `fp_inventory_items` row (pack). Atomic via a single backend endpoint `POST /inventory/items/full` that wraps both inserts in one transaction.
- Image upload (single image for now; uses StorageBackend → LocalStorage; file saved under `/storage/{org_id}/inventory/{item_id}/cover.jpg`).
- File-upload endpoint `POST /inventory/items/{id}/cover` accepts multipart.

## Files to touch
- `api/app/packs/furniture/modules/inventory/router.py` (modified — `/items/full`, `/items/{id}/cover`)
- `api/app/shared/storage/{__init__,base,local}.py` (created — `StorageBackend` + `LocalStorage`)
- `app/src/app/features/user/packs/furniture/inventory/add-product-modal.component.ts/.html` (created)

## Plan
1. Backend storage abstraction:
   - `StorageBackend.put(path, data, content_type) -> StoredFileRef`
   - `StorageBackend.url(path) -> str` (local: returns `/files/{path}` static route).
   - `LocalStorage` writes under `./storage/`.
2. Add `/items/full` endpoint that creates both rows in one transaction.
3. Add `/items/{id}/cover` accepting `UploadFile`. Stores via storage backend, persists URL.
4. Modal: form with all fields + image picker; on submit calls full endpoint, then if image, uploads.

## Verification checklist
**Backend:**
- `POST /inventory/items/full` → 201, both rows present.
- upload cover → file appears under `./storage/{org}/inventory/{item}/cover.jpg`; URL returned.
**Frontend:**
- modal → submit → product card appears with cover.

## Self-check (10 rules)
- [ ] Storage abstraction exists; no direct fs/path leak in router.
- [ ] No S3/boto3 introduced.

## Stop & report
Await "proceed" before Step 4.8.
