"""Data-access layer for the Property module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``. Matches the layered
convention (`models.py`/`schemas.py`/`router.py`/`service.py`/
`data_access.py`) enforced by `test_layered_architecture_convention.py`.

Operations grouped by entity:

  * Properties (``tbl_rp_properties``)
      insert_property, get_property_by_id, get_property_by_slug,
      list_properties, delete_property_row, count_properties_by_status
  * Property images (``tbl_rp_property_images``)
      insert_property_image, list_property_images,
      get_property_image_by_id, delete_property_image_row,
      unset_featured_for_property, bulk_update_display_orders

All helpers accept an active :class:`AsyncSession` and the required
kwargs; none of them commit / flush / refresh / rollback. The
service layer owns transaction boundaries.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.packs.real_estate.modules.property.models import Property, PropertyImage


# --- Properties ----------------------------------------------------------


def insert_property(session: AsyncSession, prop: Property) -> None:
    """Register an already-constructed Property for INSERT. Caller commits."""
    session.add(prop)


async def get_property_by_id(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    with_images: bool = False,
) -> Property | None:
    """Single-row read by PK. Returns ``None`` on miss.

    When ``with_images=True`` the gallery is eager-loaded via
    ``selectinload`` — one extra round-trip, avoiding N+1 in the
    service's detail endpoints.
    """
    stmt = select(Property).where(Property.id == property_id)
    if with_images:
        stmt = stmt.options(selectinload(Property.images))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_property_by_slug(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    slug: str,
) -> Property | None:
    """Slug is unique per org. Used by the service's slug-collision
    check before insert."""
    stmt = select(Property).where(Property.org_id == org_id, Property.slug == slug)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_properties(
    session: AsyncSession,
    *,
    statuses: list[str] | None = None,
    property_type: str | None = None,
    category: str | None = None,
    city: str | None = None,
    search: str | None = None,
    owner_id: uuid.UUID | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_by: str = "created_at",
    sort_desc: bool = True,
    page: int = 1,
    size: int = 20,
    with_images: bool = False,
) -> tuple[list[Property], int]:
    """Filtered paginated list of properties, ordered by ``sort_by``.

    ``search`` matches ``title`` (ILIKE). Numeric price range is
    inclusive on both sides. Returns ``(rows, total)`` — the count is
    a second aggregate round-trip so the caller can render pagination.
    """
    filters: list[Any] = []
    if statuses:
        filters.append(Property.status.in_(statuses))
    if property_type:
        filters.append(Property.property_type == property_type)
    if category:
        filters.append(Property.category == category)
    if city:
        filters.append(Property.city == city)
    if owner_id:
        filters.append(Property.owner_id == owner_id)
    if min_price is not None:
        filters.append(Property.price >= min_price)
    if max_price is not None:
        filters.append(Property.price <= max_price)
    if search:
        like = f"%{search}%"
        filters.append(or_(Property.title.ilike(like), Property.city.ilike(like)))

    where = and_(*filters) if filters else None
    sort_col = getattr(Property, sort_by, Property.created_at)
    order_clause = sort_col.desc() if sort_desc else sort_col.asc()

    base = select(Property)
    if with_images:
        base = base.options(selectinload(Property.images))
    if where is not None:
        base = base.where(where)
    base = base.order_by(order_clause)

    count_stmt = select(func.count()).select_from(Property)
    if where is not None:
        count_stmt = count_stmt.where(where)
    total = (await session.execute(count_stmt)).scalar_one()

    offset = max(page - 1, 0) * size
    rows = (await session.execute(base.offset(offset).limit(size))).scalars().all()
    return list(rows), int(total)


async def delete_property_row(session: AsyncSession, prop: Property) -> None:
    """Mark a Property row for DELETE. Cascades to images. Caller commits."""
    await session.delete(prop)


async def count_properties_by_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    owner_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """One-round-trip status histogram for the owner dashboard tabs.

    Returns a dict keyed by every status the org currently has rows
    for; the caller merges with the full status enum to render zeros
    for empty tabs. When ``owner_id`` is set the count is scoped to
    that user (the "My Properties" tab).
    """
    stmt = (
        select(Property.status, func.count(Property.id))
        .where(Property.org_id == org_id)
        .group_by(Property.status)
    )
    if owner_id is not None:
        stmt = stmt.where(Property.owner_id == owner_id)
    rows = (await session.execute(stmt)).all()
    return {row[0]: int(row[1]) for row in rows}


# --- Property images -----------------------------------------------------


def insert_property_image(session: AsyncSession, image: PropertyImage) -> None:
    """Register an already-constructed PropertyImage for INSERT."""
    session.add(image)


async def list_property_images(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
) -> list[PropertyImage]:
    """All images for one property, ordered by ``display_order``."""
    stmt = (
        select(PropertyImage)
        .where(PropertyImage.property_id == property_id)
        .order_by(PropertyImage.display_order.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_property_image_by_id(
    session: AsyncSession,
    *,
    image_id: uuid.UUID,
) -> PropertyImage | None:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(select(PropertyImage).where(PropertyImage.id == image_id))
    ).scalar_one_or_none()


async def delete_property_image_row(session: AsyncSession, image: PropertyImage) -> None:
    """Mark a PropertyImage row for DELETE. Caller commits."""
    await session.delete(image)


async def unset_featured_for_property(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
) -> None:
    """Bulk-clear ``is_featured`` on every image of one property.

    Used by ``service.set_featured_image`` in one UPDATE (not N) before
    flipping the target image to featured. The partial unique index
    ``uq_rp_property_images_featured`` prevents the split-second
    ambiguity from a concurrent set."""
    await session.execute(
        update(PropertyImage)
        .where(PropertyImage.property_id == property_id)
        .where(PropertyImage.is_featured.is_(True))
        .values(is_featured=False)
    )


async def bulk_update_display_orders(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    order_by_image_id: dict[uuid.UUID, int],
) -> None:
    """Rewrite ``display_order`` for a batch of images belonging to one
    property in a single UPDATE with a CASE expression — one round-trip
    regardless of gallery size (Rule: no N+1)."""
    if not order_by_image_id:
        return
    order_case = case(
        {img_id: order for img_id, order in order_by_image_id.items()},
        value=PropertyImage.id,
    )
    await session.execute(
        update(PropertyImage)
        .where(PropertyImage.property_id == property_id)
        .where(PropertyImage.id.in_(order_by_image_id.keys()))
        .values(display_order=order_case)
    )


__all__ = [
    "bulk_update_display_orders",
    "count_properties_by_status",
    "delete_property_image_row",
    "delete_property_row",
    "get_property_by_id",
    "get_property_by_slug",
    "get_property_image_by_id",
    "insert_property",
    "insert_property_image",
    "list_properties",
    "list_property_images",
    "unset_featured_for_property",
]
