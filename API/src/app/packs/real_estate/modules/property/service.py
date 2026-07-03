"""Service layer for the Property module.

Business logic, state-machine, transaction control, audit hooks.
The only layer that calls ``db.commit / flush / refresh / rollback``.

State machine
-------------

    draft ─┬─▶ published ─┬─▶ unpublished ──▶ published
           │              ├─▶ archived
           │              └─▶ sold        (terminal)
           └─▶ archived ──▶ draft         (unarchive)

Publishing requires at least one gallery image (Rule: no
unpublishable-shell listings). Every transition writes an audit row
via the shared ``core.audit.log`` helper.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.packs.real_estate.modules.property import data_access as _da
from src.app.packs.real_estate.modules.property.constants import PropertyStatus
from src.app.packs.real_estate.modules.property.models import Property, PropertyImage
from src.app.shared.files.image import ImageValidationError, validate_image_upload
from src.app.shared.storage import get_storage
from src.app.packs.real_estate.modules.property.schemas import (
    PropertyCreate,
    PropertyImageOut,
    PropertyListFilters,
    PropertyListOut,
    PropertyOut,
    PropertyUpdate,
)


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with `-`, strip edges,
    cap at 200 chars (leaves room for a random suffix within the
    220-char column)."""
    base = _SLUG_CLEAN.sub("-", text.lower()).strip("-")
    return base[:200] or "listing"


async def _unique_slug(session: AsyncSession, *, org_id: uuid.UUID, title: str) -> str:
    """Generate a slug unique within the org. Tries the plain
    slugified title first; on collision appends a short random suffix.
    After 8 collisions falls back to a longer suffix — practically
    unbounded uniqueness with predictable slug shape."""
    base = _slugify(title)
    slug = base
    for _ in range(8):
        existing = await _da.get_property_by_slug(session, org_id=org_id, slug=slug)
        if existing is None:
            return slug
        slug = f"{base}-{secrets.token_hex(2)}"
    return f"{base}-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    PropertyStatus.draft.value: {
        PropertyStatus.published.value,
        PropertyStatus.archived.value,
    },
    PropertyStatus.published.value: {
        PropertyStatus.unpublished.value,
        PropertyStatus.archived.value,
        PropertyStatus.sold.value,
    },
    PropertyStatus.unpublished.value: {
        PropertyStatus.published.value,
        PropertyStatus.archived.value,
    },
    PropertyStatus.archived.value: {
        PropertyStatus.draft.value,
    },
    PropertyStatus.sold.value: set(),
}


def _reject_transition(from_status: str, to_status: str) -> None:
    if to_status not in _ALLOWED_TRANSITIONS.get(from_status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot transition from '{from_status}' to '{to_status}'",
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _fetch_owned(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    with_images: bool = False,
) -> Property:
    """Fetch a property that must belong to ``org_id``. 404 if missing
    or wrong tenant — never leak existence across orgs."""
    prop = await _da.get_property_by_id(
        session, property_id=property_id, with_images=with_images
    )
    if prop is None or prop.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="property not found")
    return prop


def _to_out(prop: Property) -> PropertyOut:
    """Materialize a ``Property`` to ``PropertyOut``.

    Explicit field-by-field build (rather than
    ``PropertyOut.model_validate(prop)``) because ``Property.images``
    is ``lazy='raise_on_sql'`` — Pydantic's attribute walk would
    trigger the guard on properties whose gallery wasn't
    eager-loaded. Callers who want the gallery on the wire must
    load it with ``selectinload(Property.images)`` before calling.
    """
    images_loaded = "images" in prop.__dict__
    images_out: list[PropertyImageOut] = []
    featured_url: str | None = None
    if images_loaded:
        images_out = [
            PropertyImageOut.model_validate(i, from_attributes=True) for i in prop.images
        ]
        featured = next((i for i in prop.images if i.is_featured), None)
        if featured is None and prop.images:
            featured = prop.images[0]
        featured_url = featured.image_url if featured else None
    return PropertyOut(
        id=prop.id,
        org_id=prop.org_id,
        owner_id=prop.owner_id,
        title=prop.title,
        slug=prop.slug,
        description=prop.description,
        property_type=prop.property_type,
        category=prop.category,
        price=prop.price,
        currency=prop.currency,
        address_line=prop.address_line,
        city=prop.city,
        state=prop.state,
        country=prop.country,
        pincode=prop.pincode,
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        area_value=prop.area_value,
        area_unit=prop.area_unit,
        amenities=list(prop.amenities or []),
        contact_person=prop.contact_person,
        contact_phone=prop.contact_phone,
        contact_email=prop.contact_email,
        status=prop.status,
        published_at=prop.published_at,
        archived_at=prop.archived_at,
        sold_at=prop.sold_at,
        custom_data=dict(prop.custom_data or {}),
        created_at=prop.created_at,
        updated_at=prop.updated_at,
        images=images_out,
        featured_image_url=featured_url,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: PropertyCreate,
    org_default_currency: str = "INR",
) -> PropertyOut:
    """Insert a new property as a draft owned by the acting user."""
    slug = await _unique_slug(session, org_id=org_id, title=payload.title)
    prop = Property(
        org_id=org_id,
        owner_id=actor_user_id,
        title=payload.title,
        slug=slug,
        description=payload.description,
        property_type=payload.property_type.value,
        category=payload.category.value,
        price=payload.price,
        currency=payload.currency or org_default_currency,
        address_line=payload.address_line,
        city=payload.city,
        state=payload.state,
        country=payload.country,
        pincode=payload.pincode,
        bedrooms=payload.bedrooms,
        bathrooms=payload.bathrooms,
        area_value=payload.area_value,
        area_unit=payload.area_unit,
        amenities=list(payload.amenities),
        contact_person=payload.contact_person,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        status=PropertyStatus.draft.value,
        custom_data=dict(payload.custom_data),
    )
    _da.insert_property(session, prop)
    try:
        await session.flush()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="property with this slug already exists",
        ) from None
    await session.refresh(prop)
    await audit.log(
        "property.created",
        entity_type="property",
        entity_id=prop.id,
        after={"title": prop.title, "status": prop.status, "slug": prop.slug},
    )
    return _to_out(prop)


async def list_properties(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    filters: PropertyListFilters,
) -> PropertyListOut:
    """Filtered + paginated list with status-count sidebar. Uses
    ``selectinload`` for the gallery so each row's featured image
    resolves without an N+1."""
    statuses = [s.value for s in filters.statuses] if filters.statuses else None
    rows, total = await _da.list_properties(
        session,
        statuses=statuses,
        property_type=filters.property_type.value if filters.property_type else None,
        category=filters.category.value if filters.category else None,
        city=filters.city,
        search=filters.search,
        owner_id=filters.owner_id,
        min_price=float(filters.min_price) if filters.min_price is not None else None,
        max_price=float(filters.max_price) if filters.max_price is not None else None,
        sort_by=filters.sort_by,
        sort_desc=filters.sort_desc,
        page=filters.page,
        size=filters.page_size,
        with_images=True,
    )
    counts = await _da.count_properties_by_status(session, org_id=org_id)
    return PropertyListOut(
        items=[_to_out(r) for r in rows],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        status_counts=counts,
    )


async def get_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """Detail endpoint. Eager-loads the gallery so a single request
    renders the property detail page + image carousel."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    return _to_out(prop)


async def update_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    payload: PropertyUpdate,
) -> PropertyOut:
    """Partial update. Disallows edits on ``archived`` / ``sold`` —
    those are terminal display states; unarchive to draft first."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    if prop.status in {PropertyStatus.archived.value, PropertyStatus.sold.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot edit a property in '{prop.status}' state",
        )

    before = {"title": prop.title, "status": prop.status}
    data = payload.model_dump(exclude_unset=True)

    # Slug regenerates only when the title changes.
    if "title" in data and data["title"] and data["title"] != prop.title:
        prop.title = data.pop("title")
        prop.slug = await _unique_slug(session, org_id=org_id, title=prop.title)

    # Enum -> str value for storage columns.
    if "property_type" in data and data["property_type"] is not None:
        prop.property_type = data.pop("property_type").value
    if "category" in data and data["category"] is not None:
        prop.category = data.pop("category").value

    for key, value in data.items():
        setattr(prop, key, value)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="property update collided with an existing slug",
        ) from None
    await session.refresh(prop)
    await audit.log(
        "property.updated",
        entity_type="property",
        entity_id=prop.id,
        before=before,
        after={"title": prop.title, "status": prop.status},
    )
    return _to_out(prop)


async def delete_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> None:
    """Hard delete + FK-cascade of image rows + storage cleanup of
    every physical file under
    ``./storage/{org_id}/property/{property_id}/``. The DB rows go
    first (the cascade is transactional); the filesystem sweep is
    best-effort and errors are swallowed to a log line so a partial
    cleanup never turns into a 500 for the operator."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id)
    before = {"title": prop.title, "status": prop.status, "slug": prop.slug}
    await _da.delete_property_row(session, prop)
    await session.commit()

    try:
        get_storage().delete_directory(f"{org_id}/property/{property_id}")
    except Exception as exc:  # noqa: BLE001 — cleanup is best-effort
        # Not fatal — the DB rows are gone; leftover files are dead
        # weight the ops team can sweep later. Surface via audit.
        await audit.log(
            "property.storage_cleanup_failed",
            entity_type="property",
            entity_id=property_id,
            after={"error": str(exc)},
        )

    await audit.log(
        "property.deleted",
        entity_type="property",
        entity_id=property_id,
        before=before,
    )


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


async def publish_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """``draft`` / ``unpublished`` → ``published``. Requires ≥ 1 image.
    Server sets ``published_at`` if not already set (repeat publishes
    keep the first-published timestamp)."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    _reject_transition(prop.status, PropertyStatus.published.value)
    n_images = await _da.count_property_images(session, property_id=prop.id)
    if n_images < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="publish requires at least one image",
        )
    prop.status = PropertyStatus.published.value
    if prop.published_at is None:
        prop.published_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(prop)
    await audit.log(
        "property.published",
        entity_type="property",
        entity_id=prop.id,
        after={"published_at": prop.published_at.isoformat() if prop.published_at else None},
    )
    return _to_out(prop)


async def unpublish_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """``published`` → ``unpublished``. Keeps ``published_at`` so
    analytics can distinguish "never published" from "hidden after
    publication"."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    _reject_transition(prop.status, PropertyStatus.unpublished.value)
    prop.status = PropertyStatus.unpublished.value
    await session.commit()
    await session.refresh(prop)
    await audit.log(
        "property.unpublished", entity_type="property", entity_id=prop.id
    )
    return _to_out(prop)


async def archive_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """From ``draft`` / ``published`` / ``unpublished`` → ``archived``.
    Terminal display state; owner can unarchive (Step: `unarchive`
    below) to bring it back to draft."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    _reject_transition(prop.status, PropertyStatus.archived.value)
    prop.status = PropertyStatus.archived.value
    prop.archived_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(prop)
    await audit.log(
        "property.archived",
        entity_type="property",
        entity_id=prop.id,
        after={"archived_at": prop.archived_at.isoformat() if prop.archived_at else None},
    )
    return _to_out(prop)


async def unarchive_property(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """``archived`` → ``draft``. Clears ``archived_at`` so re-archiving
    later resets the timestamp."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    _reject_transition(prop.status, PropertyStatus.draft.value)
    prop.status = PropertyStatus.draft.value
    prop.archived_at = None
    await session.commit()
    await session.refresh(prop)
    await audit.log(
        "property.unarchived", entity_type="property", entity_id=prop.id
    )
    return _to_out(prop)


async def mark_sold(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
) -> PropertyOut:
    """``published`` → ``sold``. Terminal — no further transitions."""
    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id, with_images=True)
    _reject_transition(prop.status, PropertyStatus.sold.value)
    prop.status = PropertyStatus.sold.value
    prop.sold_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(prop)
    await audit.log(
        "property.sold",
        entity_type="property",
        entity_id=prop.id,
        after={"sold_at": prop.sold_at.isoformat() if prop.sold_at else None},
    )
    return _to_out(prop)


# ---------------------------------------------------------------------------
# Image gallery
# ---------------------------------------------------------------------------

# Batch upload cap. Multipart POST accepts up to this many files per
# request; more must be split across calls. Keeps a single request's
# memory profile bounded (5 MB × 20 files = 100 MB worst-case).
_MAX_UPLOAD_BATCH = 20


async def upload_property_images(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    files: list[tuple[str, bytes, str | None]],
) -> list[PropertyImage]:
    """Validate + persist a batch of images.

    ``files`` is a list of ``(filename, data, content_type)`` tuples so
    the service is independent of FastAPI's ``UploadFile`` type (also
    trivially testable). All bytes are validated up front — a partial
    batch is never persisted. On any failure the DB rolls back and
    every file already written to disk in this call is removed.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no files uploaded"
        )
    if len(files) > _MAX_UPLOAD_BATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"upload batch too large (max {_MAX_UPLOAD_BATCH})",
        )

    prop = await _fetch_owned(session, org_id=org_id, property_id=property_id)

    # Validate every file BEFORE touching disk or the DB.
    validated: list[tuple[uuid.UUID, bytes, str, str]] = []
    for _, data, _client_ct in files:
        try:
            mime, ext = validate_image_upload(data)
        except ImageValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from None
        validated.append((uuid.uuid4(), data, mime, ext))

    existing_count = await _da.count_property_images(session, property_id=prop.id)
    storage = get_storage()

    written_paths: list[str] = []
    inserted: list[PropertyImage] = []
    try:
        for i, (image_id, data, mime, ext) in enumerate(validated):
            path = f"{org_id}/property/{prop.id}/{image_id}.{ext}"
            ref = storage.put(path, data, content_type=mime)
            written_paths.append(path)
            image = PropertyImage(
                id=image_id,
                org_id=org_id,
                property_id=prop.id,
                image_path=ref.path,
                image_url=ref.url,
                content_type=mime,
                size_bytes=len(data),
                display_order=existing_count + i,
                is_featured=(existing_count == 0 and i == 0),
            )
            _da.insert_property_image(session, image)
            inserted.append(image)
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        for path in written_paths:
            try:
                storage.delete(path)
            except Exception:  # noqa: BLE001
                pass
        raise

    for image in inserted:
        await session.refresh(image)

    await audit.log(
        "property.images_uploaded",
        entity_type="property",
        entity_id=prop.id,
        after={"count": len(inserted), "image_ids": [str(i.id) for i in inserted]},
    )
    return inserted


async def _fetch_image_owned(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    image_id: uuid.UUID,
) -> PropertyImage:
    """Load an image that must belong to both ``property_id`` and
    ``org_id``. 404 across every mismatch so we never leak whether
    an id exists in a different property or a different org."""
    image = await _da.get_property_image_by_id(session, image_id=image_id)
    if image is None or image.org_id != org_id or image.property_id != property_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="image not found"
        )
    return image


async def delete_property_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    image_id: uuid.UUID,
) -> None:
    """Delete one image row + its physical file. If the deleted image
    was the featured one, promote the surviving image with the lowest
    ``display_order`` so the gallery still has a featured image."""
    await _fetch_owned(session, org_id=org_id, property_id=property_id)
    image = await _fetch_image_owned(
        session, org_id=org_id, property_id=property_id, image_id=image_id
    )
    was_featured = image.is_featured
    path = image.image_path

    await _da.delete_property_image_row(session, image)
    await session.commit()

    if was_featured:
        remaining = await _da.list_property_images(session, property_id=property_id)
        if remaining:
            promoted = remaining[0]  # lowest display_order (list is sorted asc)
            promoted.is_featured = True
            await session.commit()
            await session.refresh(promoted)

    try:
        get_storage().delete(path)
    except Exception as exc:  # noqa: BLE001 — best-effort
        await audit.log(
            "property.storage_cleanup_failed",
            entity_type="property_image",
            entity_id=image_id,
            after={"error": str(exc)},
        )

    await audit.log(
        "property.image_deleted",
        entity_type="property_image",
        entity_id=image_id,
        before={"property_id": str(property_id), "was_featured": was_featured},
    )


async def reorder_property_images(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    image_ids: list[uuid.UUID],
) -> list[PropertyImage]:
    """Rewrite ``display_order`` from the passed sequence. Rejects
    with 400 when the passed ids aren't exactly the property's
    existing gallery (no adds, no drops).

    Single UPDATE via ``CASE`` — no N+1 regardless of gallery size."""
    await _fetch_owned(session, org_id=org_id, property_id=property_id)
    current = await _da.list_property_images(session, property_id=property_id)
    current_ids = {i.id for i in current}
    requested = set(image_ids)
    if current_ids != requested or len(image_ids) != len(requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reorder must contain every image id exactly once",
        )
    order_map = {img_id: idx for idx, img_id in enumerate(image_ids)}
    await _da.bulk_update_display_orders(
        session, property_id=property_id, order_by_image_id=order_map
    )
    await session.commit()
    fresh = await _da.list_property_images(session, property_id=property_id)
    await audit.log(
        "property.images_reordered",
        entity_type="property",
        entity_id=property_id,
        after={"order": [str(i.id) for i in fresh]},
    )
    return fresh


async def set_featured_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    image_id: uuid.UUID,
) -> PropertyImage:
    """Bulk-clear ``is_featured`` on every image of the property, then
    set the target image to featured. Two UPDATEs, one commit; the
    partial unique index prevents the intermediate state from being
    visible to concurrent readers."""
    await _fetch_owned(session, org_id=org_id, property_id=property_id)
    image = await _fetch_image_owned(
        session, org_id=org_id, property_id=property_id, image_id=image_id
    )
    if image.is_featured:
        return image  # already featured — no-op keeps the endpoint idempotent
    await _da.unset_featured_for_property(session, property_id=property_id)
    image.is_featured = True
    await session.commit()
    await session.refresh(image)
    await audit.log(
        "property.image_featured",
        entity_type="property_image",
        entity_id=image.id,
        after={"property_id": str(property_id)},
    )
    return image


__all__ = [
    "archive_property",
    "create_property",
    "delete_property",
    "delete_property_image",
    "get_property",
    "list_properties",
    "mark_sold",
    "publish_property",
    "reorder_property_images",
    "set_featured_image",
    "unarchive_property",
    "unpublish_property",
    "update_property",
    "upload_property_images",
]
