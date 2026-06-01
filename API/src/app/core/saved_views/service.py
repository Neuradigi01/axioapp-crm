"""Service layer for `saved_views`.

Responsibilities:

1. List the views the current caller can see — owned + shared within
   the same org. Owner ordering first, then shared, then alphabetical.
2. Create / update / delete with the right gates:
   - Uniqueness on ``(owner_user_id, entity, name)`` → 409 on collision.
   - Update / delete: caller must own the view → 403 otherwise.
3. The `shared` toggle just flips the column; no extra plumbing needed
   because the FE re-fetches `list()` after a mutation.

Owner identity:
  - We compare against ``User.legacy_uuid``, the UUID the rest of the
    codebase uses for cross-table user references. Routers extract it
    from ``caller.legacy_uuid`` and pass it in as ``user_id``.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.saved_views.models import SavedView
from src.app.core.saved_views.schemas import (
    SavedViewCreate,
    SavedViewUpdate,
)


async def list_views(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    entity: str,
) -> list[SavedView]:
    """Views the current user can see for `entity`.

    Returns owned views first, then shared views from other owners.
    Within each bucket, ordered alphabetically by ``name`` (case-sensitive
    — the existing list pages are case-sensitive too and saved view
    names are operator-chosen, so collation surprises are rare).
    """
    stmt = (
        select(SavedView)
        .where(
            SavedView.org_id == org_id,
            SavedView.entity == entity,
            or_(
                SavedView.owner_user_id == user_id,
                SavedView.shared.is_(True),
            ),
        )
        # Owned first (False sorts before True for an "is-not-mine" flag).
        .order_by(
            (SavedView.owner_user_id != user_id).asc(),
            SavedView.name.asc(),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def get_view(
    session: AsyncSession,
    *,
    view_id: uuid.UUID,
) -> SavedView | None:
    """Fetch a single view by id. RLS keeps cross-tenant rows invisible;
    we do not enforce owner/shared here — `list_views` already filters
    the menu, and the mutation helpers explicitly check ownership."""
    result = await session.execute(
        select(SavedView).where(SavedView.id == view_id)
    )
    return result.scalar_one_or_none()


async def create_view(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: SavedViewCreate,
) -> SavedView:
    """Insert a new view owned by `user_id`. Pre-checks
    `(owner, entity, name)` and returns 409 on duplicate.

    The pre-check is the primary mechanism here rather than catching
    ``IntegrityError`` post-commit — a failed commit inside the
    request transaction leaves the asyncpg connection in a "txn
    aborted" state that has tripped up the test event loop in this
    codebase before. The unique index in 0071 stays as a backstop
    against the (rare) concurrent-insert race.
    """
    existing = await _find_view_by_name(
        session, owner_user_id=user_id, entity=payload.entity, name=payload.name
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"a saved view named {payload.name!r} already exists for "
                f"this user + entity"
            ),
        )

    view = SavedView(
        org_id=org_id,
        owner_user_id=user_id,
        entity=payload.entity,
        name=payload.name,
        config=_dump_config(payload.config),
        shared=payload.shared,
    )
    session.add(view)
    await session.commit()
    await session.refresh(view)
    return view


async def update_view(
    session: AsyncSession,
    *,
    view_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: SavedViewUpdate,
) -> SavedView:
    """Patch an existing view. 404 if missing; 403 if caller is not
    the owner (shared views are read-only for non-owners)."""
    view = await get_view(session, view_id=view_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="saved view not found",
        )
    if view.owner_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the owner can edit this saved view",
        )

    changes = payload.model_dump(exclude_unset=True)
    if "config" in changes and changes["config"] is not None:
        cfg = payload.config
        changes["config"] = _dump_config(cfg) if cfg is not None else None

    # If the rename targets a name another of this user's views already
    # holds, pre-emptively 409 — same reasoning as `create_view`.
    if "name" in changes and changes["name"] != view.name:
        clash = await _find_view_by_name(
            session,
            owner_user_id=user_id,
            entity=view.entity,
            name=changes["name"],
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "a saved view with that name already exists for this user"
                ),
            )

    for key, value in changes.items():
        setattr(view, key, value)

    await session.commit()
    await session.refresh(view)
    return view


async def delete_view(
    session: AsyncSession,
    *,
    view_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete. 404 if missing; 403 if caller doesn't own it."""
    view = await get_view(session, view_id=view_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="saved view not found",
        )
    if view.owner_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the owner can delete this saved view",
        )
    await session.delete(view)
    await session.commit()


async def _find_view_by_name(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    entity: str,
    name: str,
) -> SavedView | None:
    """Look up the (owner, entity, name) tuple — the unique constraint
    on `saved_views`. Used by create / rename to surface 409 without
    relying on the commit-side IntegrityError path."""
    result = await session.execute(
        select(SavedView).where(
            SavedView.owner_user_id == owner_user_id,
            SavedView.entity == entity,
            SavedView.name == name,
        )
    )
    return result.scalar_one_or_none()


def _dump_config(cfg: Any) -> dict[str, Any]:
    """Convert a Pydantic ``SavedViewConfig`` into the JSONB-bound dict
    the model column expects. Strips keys whose value is ``None`` so the
    persisted JSON stays compact (FE treats missing == default)."""
    raw = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)
    return {k: v for k, v in raw.items() if v is not None}


__all__ = [
    "create_view",
    "delete_view",
    "get_view",
    "list_views",
    "update_view",
]
