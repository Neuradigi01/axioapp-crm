# Catalog — Image Upload Implementation Plan

**Feature:** "Add Product" modal mein image upload — local filesystem storage, `python-magic` (libmagic) MIME validation, product card grid pe thumbnail.

**Status:** Plan finalized. Implementation pending user "proceed" signal.

**Author:** Claude · **Date:** 2026-06-05 · **Branch:** `dev`

---

## 1. Goal

Catalog ke product entries ke saath ek cover image associate karne ka end-to-end flow:

- Operator "Add Product" modal kholta hai → SKU/Name/Price ke saath ek **image bhi pick** karta hai
- Backend image ko **disk pe binary** save karta hai (not base64), DB mein sirf URL store hota hai
- Catalog grid pe har product card pe **thumbnail** dikhe (emoji fallback agar image nahi hai)
- File **type/size validation server-side** ho — client-side validation sirf UX hint hai, source of truth nahi

## 2. Non-goals

Yeh **iss iteration mein nahi**:

- Multiple images per product (gallery) — Phase 4 furniture pack mein `fp_inventory_items` aayega usme handle hoga
- Image resizing / thumbnail generation (Pillow) — original-as-uploaded store karenge
- S3 / cloud storage — `StorageBackend` interface already abstract hai, future swap easy
- CDN integration
- Image cropping / rotation UI
- EXIF stripping (privacy) — production hardening list mein
- Bulk image upload via CSV

## 3. Design decisions (confirmed)

| # | Decision | Choice | Reasoning |
|---|----------|--------|-----------|
| 1 | Where to store image URL? | **Dedicated column** `image_url` on `catalog_items` | Single column ALTER TABLE, no new table. Cleaner than `custom_data` JSONB key access from frontend. |
| 2 | Storage backend | Existing **`StorageBackend` (LocalStorage)** | Reuse the abstraction the project already has. Future S3 swap is one class change. |
| 3 | MIME validation library | **`python-magic`** (libmagic-based) | User explicitly requested. Reads real file bytes, not trusting filename/Content-Type. |
| 4 | Image size cap | **5 MB** | Matches existing contacts-import 5 MB cap; predictable memory profile. |
| 5 | Allowed types | **JPEG, PNG, WebP** | Photo formats. GIF/BMP excluded (animation + bloat). |
| 6 | Upload flow | **Separate POST** `/catalog/{id}/image` after create | Mirrors contacts-import pattern. Two requests but simpler error handling. |
| 7 | Storage path | `catalog/{org_id}/{item_id}.{ext}` | Tenant-scoped (org_id segregation). Matches CLAUDE.md storage convention. |
| 8 | Filename source | Derived from **detected MIME** (`magic.from_buffer`) | Renamed `.exe → .jpg` ko reject karta hai. Filename trust nahi karte. |
| 9 | No image processing | Pillow **only** for QR generation (existing) | User explicitly stated. Image as-uploaded saved. |

## 4. Architecture diagram

```
Browser                                  FastAPI                                 Filesystem
  │                                         │                                       │
  │ 1. POST /api/v1/catalog                  │                                       │
  │    {sku, name, price, ...}              │                                       │
  ├────────────────────────────────────────►│                                       │
  │                                         │  ── INSERT INTO catalog_items ──►    │
  │◄────────────────────────────────────────┤                                       │
  │   201 { id: "abc-123", ... }            │                                       │
  │                                         │                                       │
  │ 2. POST /api/v1/catalog/abc-123/image    │                                       │
  │    multipart/form-data: file=sofa.jpg   │                                       │
  ├────────────────────────────────────────►│                                       │
  │                                         │  ── magic.from_buffer(bytes) ──►     │
  │                                         │  ◄── "image/jpeg"                    │
  │                                         │                                       │
  │                                         │  ── storage.put(...) ────────────►   │
  │                                         │     ./storage/catalog/{org}/         │
  │                                         │     {item}.jpg (binary, 800 KB)      │
  │                                         │                                       │
  │                                         │  ── UPDATE catalog_items            │
  │                                         │     SET image_url = '/files/...'    │
  │◄────────────────────────────────────────┤                                       │
  │   200 { ..., image_url: "/files/..." }  │                                       │
  │                                         │                                       │
  │ 3. <img src="/files/catalog/..."/>       │                                       │
  ├────────────────────────────────────────►│  static mount serves file             │
  │◄────── (binary image bytes) ────────────┤  StaticFiles(directory="./storage")   │
```

## 5. Dependency changes

### `API/requirements.txt`

Add (with platform markers — pure `python-magic` Windows pe libmagic.dll ke bina chalta nahi):

```
python-magic==0.4.27; sys_platform != "win32"
python-magic-bin==0.4.14; sys_platform == "win32"
```

- **Linux/Docker container** → `python-magic` (uses system `libmagic1`, already in [Dockerfile L7](API/Dockerfile))
- **Windows local dev** → `python-magic-bin` (bundles `libmagic.dll`)

### `API/Dockerfile`

**No change needed.** `libmagic1` already installed at line 7:
```dockerfile
apt-get install -y --no-install-recommends libmagic1
```

## 6. Database changes

### Migration: `0073_catalog_image_url`

**Type:** Pure ALTER TABLE — single nullable column added. **No new table.**

**Up:**
```sql
ALTER TABLE catalog_items
    ADD COLUMN image_url VARCHAR(500) NULL;
```

**Down:**
```sql
ALTER TABLE catalog_items
    DROP COLUMN image_url;
```

**Why these specifics:**
- `VARCHAR(500)` — well within URL length conventions (max ~80 bytes in practice: `/files/catalog/<uuid>/<uuid>.webp`)
- `NULL` — existing rows preserved with `NULL`, no backfill needed
- **No RLS change** — table already has RLS from `0015_catalog_items`

### Updated `catalog_items` shape

```
catalog_items
├── id, org_id, sku, name, category, price, currency,
├── custom_data, is_active, created_at, updated_at   ← existing
└── image_url  VARCHAR(500) NULL                      ← NEW
```

## 7. Backend changes

### 7.1 New shared module — `api/src/app/shared/files/`

Path: [API/src/app/shared/files/](API/src/app/shared/files/) (new folder)

**Files:**
- `__init__.py` — re-exports `validate_image_upload`, `ImageValidationError`, `MAX_IMAGE_SIZE_BYTES`, `ALLOWED_IMAGE_MIME`
- `image.py` — the validator

**`image.py` contract:**
```python
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

ALLOWED_IMAGE_MIME = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "image/webp": "webp",
}

class ImageValidationError(ValueError): ...

def validate_image_upload(data: bytes) -> tuple[str, str]:
    """Returns (mime, ext). Raises ImageValidationError on failure."""
```

**Validation steps inside:**
1. Empty-bytes reject
2. Size cap (`len(data) > MAX_IMAGE_SIZE_BYTES`)
3. `magic.from_buffer(data[:2048], mime=True)` → real MIME
4. MIME in allowlist? Return `(mime, ext)`. Else reject.

### 7.2 Model — `api/src/app/core/catalog/models.py`

Add one column declaration after `is_active`:
```python
image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

### 7.3 Schema — `api/src/app/core/catalog/schemas.py`

Add to `CatalogItemOut`:
```python
image_url: Optional[str] = None
```

(Not added to `CatalogItemCreate` / `CatalogItemUpdate` — image only mutated via dedicated endpoint, not JSON body.)

### 7.4 Service — `api/src/app/core/catalog/service.py`

New function:
```python
async def set_item_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    file_bytes: bytes,
) -> CatalogItem:
    item = ensure_found(await get_item(session, item_id), entity="catalog item")
    try:
        mime, ext = validate_image_upload(file_bytes)
    except ImageValidationError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    storage = get_storage()
    path = f"catalog/{org_id}/{item_id}.{ext}"
    ref = storage.put(path, file_bytes, content_type=mime)

    before = _snapshot(item)
    item.image_url = ref.url
    await session.commit()
    await session.refresh(item)

    await log_entity_change(
        action="catalog.image_uploaded",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item
```

Also extend `_SNAPSHOT_FIELDS` to include `"image_url"`.

### 7.5 Router — `api/src/app/core/catalog/router.py`

New endpoint:
```python
@router.post("/{item_id}/image", response_model=CatalogItemOut)
async def upload_item_image_endpoint(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    data = await file.read()
    item = await set_item_image(
        db, org_id=user.org_id, item_id=item_id, file_bytes=data
    )
    return CatalogItemOut.model_validate(item)
```

**Imports added:** `from fastapi import File, UploadFile`, `set_item_image` from service.

**Permission:** `catalog.write` (same as create/update — already registered).

**No new DELETE-image endpoint in this iteration** — covered by "set new image" or by deleting the product entirely. Add later if user-requested.

## 8. Frontend changes

### 8.1 API service — `app/src/app/features/user/core/catalog/catalog-api.service.ts`

**Interface update:**
```typescript
export interface CatalogItem {
  // ... existing fields
  image_url: string | null;   // ← NEW
}
```

**New method:**
```typescript
uploadImage(itemId: string, file: File): Observable<CatalogItem> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  return this.http.post<CatalogItem>(`${this.base}/${itemId}/image`, fd);
}
```

### 8.2 Modal — `app/src/app/features/user/core/catalog/add-item-modal.component.{ts,html}`

**State additions (TS):**
- `selectedFile = signal<File | null>(null)`
- `previewUrl = signal<string | null>(null)` (Object URL for preview)
- `uploadError = signal<string | null>(null)`

**Client-side guards (UX hint only — server is the source of truth):**
- Allowed MIME types in `<input accept="image/jpeg,image/png,image/webp">`
- Reject `> 5 MB` with inline error before submit

**Flow change on submit (create path):**
1. `api.create(...)` → on success get `item.id`
2. If `selectedFile()` exists → `api.uploadImage(item.id, file)` → emit final item
3. Else → emit created item as-is

**Flow change on submit (edit path):**
1. `api.update(...)` → on success
2. If new file selected → `api.uploadImage(item.id, file)` → emit updated item
3. Else → emit updated item

**HTML additions:** drop-zone + preview area at top of form:
```html
<div class="mb-4">
  <label class="block text-xs font-medium text-zinc-700">Product image</label>
  <div class="mt-1 flex items-center gap-3">
    <!-- Preview thumbnail (Object URL or existing image_url) -->
    <!-- Drag-drop area + click-to-pick -->
  </div>
  @if (uploadError(); as err) { <p class="text-xs text-red-600">{{ err }}</p> }
</div>
```

### 8.3 Card grid — `app/src/app/features/user/core/catalog/catalog.page.html`

Lines 92-113 currently show emoji square. Change to conditional:
```html
@if (item.image_url) {
  <img
    [src]="item.image_url"
    [alt]="item.name"
    class="h-12 w-12 shrink-0 rounded-md object-cover"
  />
} @else {
  <span class="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-2xl">
    {{ emojiFor(item.category) }}
  </span>
}
```

## 9. Security considerations

| Threat | Mitigation |
|--------|------------|
| Renamed `.exe → .jpg` upload | `magic.from_buffer` reads real bytes, ignores filename |
| Path traversal (`../../etc/passwd`) | `LocalStorage._abs()` already rejects paths escaping root |
| Cross-tenant access | Path starts with `{org_id}` — tenant-scoped on disk |
| Storage exhaustion (DoS) | 5 MB per-file cap; future: org-level total quota |
| Malicious payload in image | No image processing → no Pillow/ImageMagick CVE exposure. Served as binary blob via static mount. |
| `Content-Type` sniffing in browser | Static mount serves files; browser determines MIME from extension. JPEG/PNG/WebP are safe inline content types. |

**Not in scope (acknowledged gaps):**
- EXIF metadata stripping (GPS, camera serial leak possible)
- Image dimension limits (1000×1000 vs 10000×10000)
- Per-org storage quota
- Antivirus scan (ClamAV) — would be a separate hardening step

## 10. Testing checklist

### Backend (manual + automated)

- [ ] Upload valid JPEG (500 KB) → 200, `image_url` set, file on disk
- [ ] Upload valid PNG (2 MB) → 200
- [ ] Upload valid WebP → 200
- [ ] Upload GIF → 400 "Unsupported image type 'image/gif'"
- [ ] Upload PDF renamed to `.jpg` → 400 (magic detects `application/pdf`)
- [ ] Upload 6 MB JPEG → 400 "Image exceeds the 5 MB cap"
- [ ] Upload empty file → 400 "Empty file"
- [ ] Upload to non-existent product ID → 404
- [ ] Upload without `catalog.write` permission → 403
- [ ] Cross-tenant: org A user upload to org B product → 404 (RLS scope)
- [ ] Re-upload overwrites existing file at same path
- [ ] Migration up → column exists
- [ ] Migration down → column removed cleanly

### Frontend (manual)

- [ ] Pick image in create modal → submit → product appears with thumbnail
- [ ] Pick image in edit modal → submit → thumbnail updates
- [ ] Pick > 5 MB file → inline error, submit blocked
- [ ] Pick `.gif` → inline error, submit blocked
- [ ] Drag-drop file → preview shows
- [ ] Cancel modal mid-upload → no orphan request
- [ ] Card grid shows thumbnail when `image_url` set, emoji when null
- [ ] Image loads from `/files/catalog/...` URL correctly
- [ ] Old products (no image_url) still render with emoji fallback

## 11. Files touched

### New
- `API/src/app/shared/files/__init__.py`
- `API/src/app/shared/files/image.py`
- `API/alembic/versions/0073_catalog_image_url.py`

### Modified
- `API/requirements.txt` (+2 lines, platform-marked)
- `API/src/app/core/catalog/models.py` (+1 line: `image_url` column)
- `API/src/app/core/catalog/schemas.py` (+1 line: `image_url` in `CatalogItemOut`)
- `API/src/app/core/catalog/service.py` (+~30 lines: `set_item_image()` + imports + snapshot field)
- `API/src/app/core/catalog/router.py` (+~15 lines: upload endpoint + imports)
- `app/src/app/features/user/core/catalog/catalog-api.service.ts` (+1 field, +1 method)
- `app/src/app/features/user/core/catalog/add-item-modal.component.ts` (+~40 lines: file state, post-create upload)
- `app/src/app/features/user/core/catalog/add-item-modal.component.html` (+~25 lines: drop-zone, preview)
- `app/src/app/features/user/core/catalog/catalog.page.html` (~10 lines: conditional thumbnail/emoji)

**Untouched (per CLAUDE.md):**
- `Flutter/` — not part of product
- `app/src/app/features/admin/` — legacy admin panel
- `app/src/app/features/accounts/` — auth pages
- Auth modules in backend

## 12. Rollback plan

Agar production mein issue aaye:

1. **Frontend**: Revert the 4 frontend file changes — image picker disappears, grid falls back to emoji for all cards (image URLs in DB are ignored harmlessly).
2. **Backend endpoint**: Comment out the `POST /image` route. Existing rows with `image_url` continue to render via static mount.
3. **Schema**: `alembic downgrade -1` removes the column. Files on disk become orphans (cleanup script not in scope).
4. **Storage**: `rm -rf ./storage/catalog/` clears uploaded images if compliance requires.

Migration is **safe to roll back** — no data loss in core catalog rows.

## 13. Implementation order (when "proceed" given)

1. Add `python-magic` to `requirements.txt` (Docker rebuild needed)
2. Create `shared/files/image.py` + `__init__.py`
3. Create Alembic migration `0073_catalog_image_url.py`
4. Apply: `uv run alembic upgrade head`
5. Update `catalog/models.py` (add column)
6. Update `catalog/schemas.py` (add `image_url` to Out)
7. Update `catalog/service.py` (add `set_item_image`)
8. Update `catalog/router.py` (add upload endpoint)
9. Smoke test backend with curl
10. Update frontend `catalog-api.service.ts`
11. Update `add-item-modal.{ts,html}` (file picker + preview + post-create upload)
12. Update `catalog.page.html` (thumbnail in card)
13. Smoke test full flow in browser

## 14. Open questions (none currently)

Saare design decisions confirmed hain (section 3). Implementation start karne ke liye user ka "proceed" chahiye.

---

**Awaiting:** `proceed` to begin implementation in the order specified in section 13.
