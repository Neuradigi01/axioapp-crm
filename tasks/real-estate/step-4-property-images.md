# Step 4 — Property backend: multi-image gallery

**Goal:** Ship authenticated image endpoints for Property — upload one or many images, delete an image, reorder the gallery, set which image is featured. Files land on the filesystem under the locked `./storage/{org_id}/property/{property_id}/` layout, validated by the existing image validator, no S3.

**Track:** Real Estate CRM Pack
**Status:** COMPLETED
**Depends on:** Step 3 (Property CRUD live).

---

## Scope

**IN:**

1. Extend `schemas.py` with:
   - `PropertyImageUploadOut` — one image (id, image_url, display_order, is_featured).
   - `PropertyImageReorderRequest` — `{ image_ids: list[UUID] }` — new order top-to-bottom, all image_ids must belong to the property.

2. Extend `service.py` with image operations:
   - `upload_property_images(db, *, org_id, property_id, files: list[UploadFile]) -> list[PropertyImageOut]`:
     - Fetch property (404 if missing / wrong org).
     - Iterate `files`. For each:
       - Call `validate_image_upload(file)` from [shared/files/image.py](../../API/src/app/shared/files/image.py) — enforces size/type/magic bytes.
       - Compute path: `f"{org_id}/property/{property_id}/{image_id}.{ext}"`.
       - Call `storage_backend.put(path, bytes, content_type)`.
       - Call `data_access.insert_property_image` with `display_order = next_order` (append at end).
       - If this is the property's first image, set `is_featured=True` on it (default featured = first uploaded).
     - `db.flush()` between inserts to get IDs; one `db.commit()` at the end for the whole batch.
     - Rollback the whole batch and cleanup uploaded files on any failure (transactional integrity).
   - `delete_property_image(db, *, org_id, property_id, image_id) -> None`:
     - Fetch image; verify `property_id` + `org_id` match.
     - Delete file via `storage_backend.delete(path)` (add a `delete` method to the storage backend if not present).
     - DAL delete.
     - If deleted image was featured and other images exist, promote the lowest-display-order remaining image to featured.
     - Commit; audit.
   - `reorder_property_images(db, *, org_id, property_id, image_ids) -> list[PropertyImageOut]`:
     - Fetch all images for property; verify `image_ids` is a permutation of the existing IDs (no add, no drop).
     - Update `display_order` in a single UPDATE ... FROM VALUES statement (batched) — Rule: no N+1.
     - Commit; return refreshed list.
   - `set_featured_image(db, *, org_id, property_id, image_id) -> PropertyImageOut`:
     - Call DAL `unset_featured_for_property` (bulk update: all images `is_featured=False`).
     - Set target image `is_featured=True`.
     - Commit; refresh; return.

3. Extend `router.py` with:
   - `POST /api/v1/property/{id}/images` — multipart upload, accepts up to 20 files in one call. Permission: `property.write`.
   - `DELETE /api/v1/property/{id}/images/{image_id}` — delete one. Permission: `property.write`.
   - `PATCH /api/v1/property/{id}/images/reorder` — reorder. Permission: `property.write`.
   - `PATCH /api/v1/property/{id}/images/{image_id}/featured` — set featured. Permission: `property.write`.

4. Extend `PropertyOut` schema so `image_urls` and `featured_image_url` are always populated on `GET` responses (already scaffolded in Step 2; Step 3 wired via `selectinload`; Step 4 ensures the computation reads featured correctly).

5. Extend `storage/base.py` and `storage/local.py` with a `delete(path)` method if missing — need to remove image files on gallery-image delete. Confirm existence before adding (grep first).

6. Storage cleanup on property delete — Step 3's `delete_property_service` should call `storage_backend.delete_directory(f"{org_id}/property/{property_id}")` before the DB delete cascades. If Step 3 didn't wire this, add it here as a targeted fix (small, in-scope for the image lifecycle).

7. Pytest — `test_property_images.py`:
   - Upload 3 images → gallery lists 3, first is featured.
   - Upload invalid file (e.g., SVG or 6 MB) → 422, no file written, DB unchanged.
   - Reorder → `display_order` updates match request.
   - Reorder with mismatched IDs → 400.
   - Delete featured → next-order image becomes featured.
   - Set featured → exactly one `is_featured=True` (partial unique index enforces).
   - Delete property → cascade removes image rows AND storage directory (mock `storage_backend.delete_directory`).

**OUT:**

- No public unauthenticated endpoints — Step 5.
- No frontend gallery UI — Step 7.
- No image resizing / thumbnail generation. Deferred to Real Estate Phase 2 (thumbnail worker). Store originals; frontend can lazy-load.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/modules/property/schemas.py` | Modify — add ~40 lines. |
| `api/src/app/packs/real_estate/modules/property/service.py` | Modify — add ~180 lines. |
| `api/src/app/packs/real_estate/modules/property/router.py` | Modify — add ~60 lines. |
| `api/src/app/packs/real_estate/modules/property/data_access.py` | Modify — add ~30 lines (`bulk_update_display_orders`). |
| `api/src/app/shared/storage/base.py` | Modify — add `delete` + `delete_directory` abstract methods if missing. |
| `api/src/app/shared/storage/local.py` | Modify — implement `delete` + `delete_directory` (with safety check: path must start with configured storage root). |
| `api/tests/packs/real_estate/test_property_images.py` | New (~220 lines). |

**7 files, ~530 lines total.** Within Rule 8.

## Verification checklist

- [ ] Multi-file upload works via Swagger (multipart form, 3+ files, all under 5 MB, JPEG/PNG/WebP).
- [ ] Invalid file rejected (try a 6 MB image or an SVG) → 422, no file written.
- [ ] Physical files land at `./storage/{org_id}/property/{property_id}/{image_id}.jpg`.
- [ ] Reorder request updates `display_order` correctly (single UPDATE, verifiable in Postgres log).
- [ ] Delete featured → next image becomes featured atomically.
- [ ] Partial unique index prevents two `is_featured=True` for same property (try to set two).
- [ ] Property deletion removes the directory (physical files gone).
- [ ] `uv run pytest tests/packs/real_estate/test_property_images.py -v` — 7 assertions green.
- [ ] `test_layered_architecture_convention.py` still green.

## Self-check against the 10 rules

- **Rule 2** — Image table has `org_id`, RLS from Step 2; image endpoint uses org_id from JWT context, not client-provided.
- **Rule 8** — Step scope is a single feature slice (multi-image lifecycle), verifiable in one Postman session.
- **Layering** — All image endpoint transactions in `service.py`; DAL adds one bulk-update helper, no commit.
- **DB efficiency** — Reorder is single UPDATE with VALUES table (not N per image). Unset-featured is single UPDATE. Upload batch shares one transaction.
- **Security** — `storage_backend.delete` (and `delete_directory`) guard the path — must be under the configured `STORAGE_ROOT`. Prevents path traversal.

## Stop and report

- **Files changed:** 7 files.
- **What you can verify:** Swagger multipart upload, filesystem inspection under `./storage/`, reorder + featured toggle via curl, pytest.
- **Tests added:** 7 assertions.
- **Self-check:** 10-rule block + storage-path-safety note.
- **Awaiting 'proceed'** — Step 5 adds the public unauthenticated endpoints with Fernet-encrypted tokens.
