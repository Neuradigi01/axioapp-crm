"""Service layer for the catalog module.

Same `custom_data` validation engine as contacts / leads / appointments
— entity_type `catalog_item`. Filtered list supports:

  - `q`     — ILIKE across name + sku (autocomplete picker uses this)
  - `category` — exact match on the free-text column (back-compat)
  - `category_id` — FK match on the new category entity (preferred)
  - `active_only` — drops `is_active=false` rows

A duplicate `(org_id, sku)` violates the unique constraint at the DB
level; we catch the IntegrityError and surface a 409 with a friendly
message rather than letting the raw DB error escape.

Extended by the catalog review (0163):
  * ``delete_item`` now cleans up the primary + gallery image files on
    disk (C1). Previously left them orphaned.
  * ``add_gallery_image`` / ``remove_gallery_image`` for the multi-
    image gallery (C5).
  * Category CRUD (C2).
  * ``bulk_import_items`` for the bulk-import wizard (C8).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog import data_access as _da
from src.app.core.catalog.models import CatalogCategory, CatalogItem
from src.app.core.catalog.schemas import (
    CatalogCategoryCreate,
    CatalogCategoryUpdate,
    CatalogItemBulkImportRequest,
    CatalogItemBulkImportResult,
    CatalogItemBulkImportRowError,
    CatalogItemCreate,
    CatalogItemUpdate,
)
from src.app.shared import validators as shared_validators
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found
from src.app.shared.files import (
    ImageValidationError,
    validate_image_upload,
)
from src.app.shared.storage import get_storage

_log = logging.getLogger(__name__)

_CATALOG_ENTITY = "catalog_item"
_MAX_GALLERY = 8  # cover + up to 8 secondaries; a reasonable card-shape cap


_SNAPSHOT_FIELDS = (
    "id",
    "sku",
    "name",
    "description",
    "category",
    "category_id",
    "price",
    "cost_price",
    "currency",
    "is_active",
    "tags",
    "image_url",
    "image_urls",
    "custom_data",
)


def _snapshot(item: CatalogItem) -> dict[str, Any]:
    return snapshot(item, fields=_SNAPSHOT_FIELDS)


def _slugify(name: str) -> str:
    """Category slug — lower, hyphen-separated, alnum only. Not
    unique-constrained on the DB side so a collision falls through
    cleanly; used only for display / future URL routing."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _storage_path_from_url(url: str) -> str | None:
    """Reverse of ``LocalStorage.url()``. Returns the storage-relative
    path so ``storage.delete()`` can find it, or ``None`` when the URL
    doesn't look like a locally-served file (e.g. a full https:// URL
    from a future S3 backend)."""
    if not url:
        return None
    # Local storage prefixes /files/<path>; strip that prefix.
    if url.startswith("/files/"):
        return url[len("/files/") :]
    if url.startswith("files/"):
        return url[len("files/") :]
    # Unknown shape — don't try to delete; log + skip.
    return None


async def _delete_stored_image(url: str | None) -> None:
    """Best-effort delete of a stored image file. Swallows errors so
    a missing file / permission blip never blocks the DB delete."""
    if not url:
        return
    path = _storage_path_from_url(url)
    if path is None:
        return
    try:
        storage = get_storage()
        storage.delete(path)
    except Exception:  # noqa: BLE001 — storage layer is best-effort
        _log.exception("catalog: failed to delete stored image %s", path)


# --- Category CRUD (C2) ----------------------------------------------------


async def list_categories(
    session: AsyncSession, *, org_id: uuid.UUID, active_only: bool = False
) -> list[CatalogCategory]:
    stmt = select(CatalogCategory).where(CatalogCategory.org_id == org_id)
    if active_only:
        stmt = stmt.where(CatalogCategory.is_active.is_(True))
    stmt = stmt.order_by(
        CatalogCategory.display_order.asc(), CatalogCategory.name.asc()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_category(
    session: AsyncSession, *, category_id: uuid.UUID
) -> CatalogCategory | None:
    result = await session.execute(
        select(CatalogCategory).where(CatalogCategory.id == category_id)
    )
    return result.scalar_one_or_none()


async def create_category(
    session: AsyncSession, *, org_id: uuid.UUID, payload: CatalogCategoryCreate
) -> CatalogCategory:
    cat = CatalogCategory(
        org_id=org_id,
        name=payload.name,
        slug=_slugify(payload.name),
        description=payload.description,
        icon_emoji=payload.icon_emoji,
        color_hex=payload.color_hex,
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    session.add(cat)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"category {payload.name!r} already exists in this org",
        ) from exc
    await session.refresh(cat)
    await log_entity_change(
        action="catalog.category.created",
        entity_type="catalog_category",
        entity_id=cat.id,
        after={"name": cat.name, "slug": cat.slug},
    )
    return cat


async def update_category(
    session: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: CatalogCategoryUpdate,
) -> CatalogCategory:
    cat = ensure_found(await get_category(session, category_id=category_id), entity="category")
    before = {"name": cat.name, "slug": cat.slug, "is_active": cat.is_active}
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(cat, key, value)
    if "name" in changes and changes["name"]:
        cat.slug = _slugify(changes["name"])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"category name conflict: {exc.orig!s}",
        ) from exc
    await session.refresh(cat)
    await log_entity_change(
        action="catalog.category.updated",
        entity_type="catalog_category",
        entity_id=cat.id,
        before=before,
        after={"name": cat.name, "slug": cat.slug, "is_active": cat.is_active},
    )
    return cat


async def delete_category(session: AsyncSession, *, category_id: uuid.UUID) -> None:
    cat = ensure_found(await get_category(session, category_id=category_id), entity="category")
    before = {"name": cat.name, "slug": cat.slug}
    cat_uuid = cat.id
    await session.delete(cat)
    await session.commit()
    # ON DELETE SET NULL on tbl_catalog_items.category_id — items are
    # unlinked, not deleted.
    await log_entity_change(
        action="catalog.category.deleted",
        entity_type="catalog_category",
        entity_id=cat_uuid,
        before=before,
    )


async def _resolve_category_free_text(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    category_id: uuid.UUID | None,
    category: str | None,
) -> tuple[str | None, uuid.UUID | None]:
    """Given the two shapes callers can send, return the pair
    ``(free_text_category, category_id)`` for the row.

    Priority: ``category_id`` wins if supplied. Otherwise, if
    ``category`` free-text is set, look up (or auto-create) the
    matching category so ``category_id`` is populated. The free-text
    column keeps mirroring so back-compat readers still see it."""
    if category_id is not None:
        cat = await get_category(session, category_id=category_id)
        if cat is None or cat.org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"category_id {category_id} not found in this org",
            )
        return cat.name, cat.id
    if category:
        # Auto-create-if-missing behaviour matches the free-text
        # legacy: an operator who types a new category on the item
        # form has the category quietly created. Owner can then edit
        # / colour / reorder on the settings page.
        existing = (
            await session.execute(
                select(CatalogCategory).where(
                    CatalogCategory.org_id == org_id,
                    CatalogCategory.name == category,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = CatalogCategory(
                org_id=org_id,
                name=category,
                slug=_slugify(category),
            )
            session.add(existing)
            await session.flush()
        return existing.name, existing.id
    return None, None


# --- Item CRUD ---


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> CatalogItem | None:
    return await _da.get_catalog_item_by_id(session, item_id)


async def create_item(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: CatalogItemCreate,
) -> CatalogItem:
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_CATALOG_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
    )
    category_name, category_id = await _resolve_category_free_text(
        session, org_id=org_id, category_id=payload.category_id, category=payload.category
    )
    item = CatalogItem(
        org_id=org_id,
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        category=category_name,
        category_id=category_id,
        price=payload.price,
        cost_price=payload.cost_price,
        currency=payload.currency,
        is_active=payload.is_active,
        tags=payload.tags,
        custom_data=cleaned_custom,
    )
    _da.insert_catalog_item(session, item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SKU {payload.sku!r} already exists in this org",
        ) from exc
    await session.refresh(item)

    await log_entity_change(
        action="catalog.created",
        entity_type="catalog_item",
        entity_id=item.id,
        after=_snapshot(item),
    )
    return item


async def update_item(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
) -> CatalogItem:
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    before = _snapshot(item)
    changes = payload.model_dump(exclude_unset=True)
    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_CATALOG_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    # Category resolution: same rules as create. Only run when either
    # key was supplied in the PATCH — leave the row untouched otherwise.
    if "category" in changes or "category_id" in changes:
        category_name, category_id = await _resolve_category_free_text(
            session,
            org_id=item.org_id,
            category_id=changes.get("category_id"),
            category=changes.get("category"),
        )
        changes["category"] = category_name
        changes["category_id"] = category_id
    for key, value in changes.items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)

    await log_entity_change(
        action="catalog.updated",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item


async def delete_item(session: AsyncSession, *, item_id: uuid.UUID) -> None:
    """C1 — Delete the item row *and* clean up every stored image
    (primary cover + gallery). Previously the row was dropped but the
    files stayed on disk forever."""
    item = ensure_found(await get_item(session, item_id), entity="catalog item")
    before = _snapshot(item)
    item_uuid = item.id
    # Snapshot URLs before the row is gone so we can chase them.
    urls = list(item.image_urls or [])
    if item.image_url:
        urls.append(item.image_url)

    await _da.delete_catalog_item_row(session, item)
    await session.commit()

    for url in urls:
        await _delete_stored_image(url)

    await log_entity_change(
        action="catalog.deleted",
        entity_type="catalog_item",
        entity_id=item_uuid,
        before=before,
    )


async def set_item_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    file_bytes: bytes,
) -> CatalogItem:
    """Validate + persist the primary cover image for `item_id`.

    libmagic sniffs the real MIME from the bytes (filename ignored),
    storage path is tenant-scoped ``catalog/{org_id}/{item_id}.{ext}``,
    and the resulting public URL lands on ``image_url``.

    If replacing an existing cover whose extension changed (JPEG →
    PNG), the old file path is no longer overwritten by the new write
    (different extension), so we explicitly delete it (C1 correlate)."""
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    try:
        mime, ext = validate_image_upload(file_bytes)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    storage = get_storage()
    storage_path = f"catalog/{org_id}/{item_id}.{ext}"
    ref = storage.put(storage_path, file_bytes, content_type=mime)

    # If the previous cover lived at a different extension, its path
    # is different from the new one — clean it up so we don't leak.
    if item.image_url:
        old_path = _storage_path_from_url(item.image_url)
        if old_path and old_path != storage_path:
            await _delete_stored_image(item.image_url)

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


# --- Gallery (C5) ---------------------------------------------------------


async def add_gallery_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    file_bytes: bytes,
) -> CatalogItem:
    """Append a new image to the gallery. Distinct from ``image_url``
    (the primary cover) — gallery images are numbered for storage
    and appended to the ``image_urls`` array in order."""
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    if len(item.image_urls or []) >= _MAX_GALLERY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"gallery cap reached ({_MAX_GALLERY} images)",
        )

    try:
        mime, ext = validate_image_upload(file_bytes)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    storage = get_storage()
    # Sequential slot number so re-adds don't collide.
    slot = len(item.image_urls or [])
    while True:
        candidate = f"catalog/{org_id}/{item_id}-g{slot}.{ext}"
        # If the slot is still free on disk, use it. Otherwise bump.
        if _storage_path_from_url(candidate) not in {
            _storage_path_from_url(u) for u in (item.image_urls or [])
        }:
            break
        slot += 1
    ref = storage.put(candidate, file_bytes, content_type=mime)

    before = _snapshot(item)
    item.image_urls = list(item.image_urls or []) + [ref.url]
    await session.commit()
    await session.refresh(item)

    await log_entity_change(
        action="catalog.gallery_added",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item


async def remove_gallery_image(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    index: int,
) -> CatalogItem:
    """Remove the gallery entry at ``index``. Also deletes the file
    on disk. Silently no-ops for an out-of-range index (idempotent)."""
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    urls = list(item.image_urls or [])
    if index < 0 or index >= len(urls):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"gallery index {index} out of range (0..{len(urls) - 1})",
        )

    removed_url = urls.pop(index)
    before = _snapshot(item)
    item.image_urls = urls
    await session.commit()
    await session.refresh(item)

    await _delete_stored_image(removed_url)

    await log_entity_change(
        action="catalog.gallery_removed",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item


# --- Bulk import (C8) -----------------------------------------------------

# Shape constraints applied per-row in `bulk_import_items` on top of the
# Pydantic min/max_length checks. Failures land in the response's `errors`
# list instead of 422-ing the whole batch — same UX as contacts / leads.
_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,63}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PRICE_MAX = 1_000_000_000  # 1B cap — covers real furniture pricing with headroom


def _validate_bulk_import_row(
    idx: int, row: Any
) -> CatalogItemBulkImportRowError | None:
    """Server-side per-row validators for the bulk-import wizard.

    Returns the first shape failure as a `CatalogItemBulkImportRowError`,
    or `None` if the row passes every check. Applied on top of the
    Pydantic schema — Pydantic already guards min/max_length + price>=0;
    this catches SKU character class, name content, currency casing,
    and price upper bound.
    """
    if not _SKU_RE.match(row.sku):
        return CatalogItemBulkImportRowError(
            row_index=idx,
            sku=row.sku,
            column="sku",
            value=row.sku,
            reason="SKU must be 2–64 chars, uppercase alphanumeric + '-' or '_'",
        )
    try:
        shared_validators.validate_name(row.name)
    except shared_validators.ValidationError as exc:
        return CatalogItemBulkImportRowError(
            row_index=idx,
            sku=row.sku,
            column="name",
            value=row.name,
            reason=exc.reason,
        )
    if row.currency and not _CURRENCY_RE.match(row.currency):
        return CatalogItemBulkImportRowError(
            row_index=idx,
            sku=row.sku,
            column="currency",
            value=row.currency,
            reason="currency must be a 3-letter ISO 4217 code (e.g. INR, USD)",
        )
    if row.price is not None and row.price > _PRICE_MAX:
        return CatalogItemBulkImportRowError(
            row_index=idx,
            sku=row.sku,
            column="price",
            value=str(row.price),
            reason=f"price out of range 0–{_PRICE_MAX:,}",
        )
    return None


async def bulk_import_items(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: CatalogItemBulkImportRequest,
) -> CatalogItemBulkImportResult:
    """Bulk-insert catalog rows. Dedup by SKU: already-existing SKUs
    are counted as ``skipped`` (bulk-import doesn't overwrite; the
    individual PATCH endpoint handles that). Malformed rows land in
    ``errors``."""
    # Snapshot existing SKUs so we can skip without querying per row.
    existing_skus = {
        row[0]
        for row in (
            await session.execute(
                select(CatalogItem.sku).where(CatalogItem.org_id == org_id)
            )
        ).all()
    }
    # Also skip duplicates within the same batch.
    seen_in_batch: set[str] = set()
    inserted = 0
    skipped = 0
    errors: list[CatalogItemBulkImportRowError] = []

    for i, row in enumerate(payload.rows):
        shape_error = _validate_bulk_import_row(i, row)
        if shape_error is not None:
            errors.append(shape_error)
            continue
        try:
            if row.sku in existing_skus or row.sku in seen_in_batch:
                skipped += 1
                continue
            if payload.dry_run:
                inserted += 1
                seen_in_batch.add(row.sku)
                continue
            _category_name, _category_id = await _resolve_category_free_text(
                session, org_id=org_id, category_id=None, category=row.category
            )
            item = CatalogItem(
                org_id=org_id,
                sku=row.sku,
                name=row.name,
                description=row.description,
                category=_category_name,
                category_id=_category_id,
                price=row.price,
                cost_price=row.cost_price,
                currency=row.currency,
                is_active=row.is_active,
                tags=row.tags,
                custom_data={},
            )
            _da.insert_catalog_item(session, item)
            inserted += 1
            seen_in_batch.add(row.sku)
        except Exception as exc:  # noqa: BLE001 — collect per-row failures
            errors.append(
                CatalogItemBulkImportRowError(
                    row_index=i, sku=row.sku, reason=str(exc)
                )
            )

    if payload.dry_run:
        # Roll back any category upserts done during dry-run so the
        # preview truly doesn't change state.
        await session.rollback()
    else:
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            errors.append(
                CatalogItemBulkImportRowError(
                    row_index=-1, sku="—", reason=f"commit failed: {exc.orig!s}"
                )
            )
            inserted = 0

        await log_entity_change(
            action="catalog.bulk_imported",
            entity_type="catalog_item",
            after={
                "inserted": inserted,
                "skipped": skipped,
                "errors": len(errors),
            },
        )

    return CatalogItemBulkImportResult(
        inserted=inserted,
        skipped=skipped,
        errors=errors,
        dry_run=payload.dry_run,
    )


async def list_items(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    category_id: uuid.UUID | None = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CatalogItem], int]:
    """Paginated filtered list. `q` ILIKEs across name + sku."""
    return await _da.list_catalog_items_query(
        session,
        q=q,
        category=category,
        category_id=category_id,
        active_only=active_only,
        page=page,
        size=size,
    )


__all__ = [
    "add_gallery_image",
    "bulk_import_items",
    "create_category",
    "create_item",
    "delete_category",
    "delete_item",
    "get_category",
    "get_item",
    "list_categories",
    "list_items",
    "remove_gallery_image",
    "set_item_image",
    "update_category",
    "update_item",
]
