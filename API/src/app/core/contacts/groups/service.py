"""Service layer for contact-groups CRUD + audience resolution.

Three groups of functions:

  1. **CRUD** — `create_group`, `update_group`, `delete_group`,
     `get_group`, `list_groups`. Mode is set at creation and
     immutable; an attempted mode switch is rejected at the schema
     layer (`GroupUpdate` doesn't expose `is_dynamic`).

  2. **Resolution** — `resolve_group_contacts(group_id) -> list[uuid]`:
     - Dynamic: applies `filter_json` to the contacts table via the
       shared predicate builder.
     - Static: SELECTs `contact_group_members.contact_id` for the group.
     Both return sorted UUIDs so chunking / dedup downstream is stable.

  3. **Preview** — `preview_audience_size(...)`: returns just the
     count without materialising rows. Used by the Step 3.5.9
     campaign audience builder to show "82 contacts will receive
     this" before the operator commits.

All reads/writes go through the active session — the ORM tenant
filter + Postgres RLS jointly enforce org isolation.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.audit import log_entity_change
from src.app.core.contacts.groups import data_access
from src.app.core.contacts.groups.models import ContactGroup
from src.app.core.contacts.groups.schemas import (
    GroupCreate,
    GroupFilter,
    GroupUpdate,
)


# --- reads ----------------------------------------------------------------


async def get_group(
    session: AsyncSession, group_id: uuid.UUID
) -> ContactGroup:
    row = await data_access.get_group_by_id(session, group_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="contact group not found",
        )
    return row


async def list_groups(
    session: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
) -> tuple[list[ContactGroup], int]:
    """Paginated list. Returns `(rows, total)` so the API can shape
    a `GroupListResponse` directly."""
    total = await data_access.count_groups(session)
    offset = (page - 1) * size
    rows = await data_access.list_groups_page(
        session, offset=offset, limit=size
    )
    return rows, total


# --- writes ---------------------------------------------------------------


async def create_group(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: GroupCreate,
) -> ContactGroup:
    """Insert a `contact_groups` row + (for static groups) bulk-insert
    member rows. UNIQUE(`org_id`, `name`) collisions surface as 409."""
    group = data_access.add_group(
        session,
        ContactGroup(
            org_id=org_id,
            name=payload.name,
            description=payload.description,
            is_dynamic=payload.is_dynamic,
            filter_json=(
                payload.filter_json.model_dump(exclude_none=True)
                if payload.filter_json is not None
                else None
            ),
            created_by_id=user_id,
        ),
    )
    try:
        await session.flush()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A group named '{payload.name}' already exists.",
        )

    if not payload.is_dynamic and payload.contact_ids:
        await data_access.bulk_upsert_members(
            session,
            org_id=org_id,
            group_id=group.id,
            contact_ids=payload.contact_ids,
        )

    await session.commit()
    await session.refresh(group)

    await log_entity_change(
        action="contacts.group.created",
        entity_type="contact_group",
        entity_id=group.id,
        after={
            "name": group.name,
            "is_dynamic": group.is_dynamic,
            "member_count": (
                len(payload.contact_ids or []) if not group.is_dynamic else None
            ),
        },
    )
    return group


async def update_group(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    payload: GroupUpdate,
) -> ContactGroup:
    """Partial update. `is_dynamic` mode is immutable here — schema
    doesn't expose it. Replacing `contact_ids` on a static group
    fully replaces the member set (old members deleted, new inserted)."""
    group = await get_group(session, group_id)
    changed = False

    if payload.name is not None:
        group.name = payload.name
        changed = True
    if payload.description is not None:
        group.description = payload.description
        changed = True
    if payload.filter_json is not None:
        if not group.is_dynamic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set `filter_json` on a static group.",
            )
        group.filter_json = payload.filter_json.model_dump(
            exclude_none=True
        )
        changed = True
    if payload.contact_ids is not None:
        if group.is_dynamic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set `contact_ids` on a dynamic group.",
            )
        # Replace the full member set atomically: delete old, insert new.
        await data_access.delete_members_for_group(session, group_id)
        if payload.contact_ids:
            await data_access.bulk_upsert_members(
                session,
                org_id=group.org_id,
                group_id=group_id,
                contact_ids=payload.contact_ids,
            )
        changed = True

    if not changed:
        return group

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update conflict — name may already be in use.",
        )
    await session.refresh(group)
    await log_entity_change(
        action="contacts.group.updated",
        entity_type="contact_group",
        entity_id=group_id,
        after={"name": group.name},
    )
    return group


async def delete_group(
    session: AsyncSession, *, group_id: uuid.UUID
) -> None:
    """Hard delete. CASCADE on the FK drops the member rows.

    Campaigns that reference the group via `audience_filter.group_id`
    are NOT touched here — Step 3.5.9's resolver treats a missing
    group as an empty audience (the campaign sends to zero contacts
    with a clear error message)."""
    group = await get_group(session, group_id)
    name = group.name
    await data_access.delete_group_row(session, group)
    await session.commit()
    await log_entity_change(
        action="contacts.group.deleted",
        entity_type="contact_group",
        entity_id=group_id,
        before={"name": name},
    )


# --- resolution -----------------------------------------------------------


async def resolve_group_contacts(
    session: AsyncSession, *, group_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return the list of contact IDs this group currently resolves to.

    Dynamic groups run the saved `filter_json` against `contacts`.
    Static groups SELECT `contact_group_members.contact_id`.
    Both sort the result so the downstream chunker is deterministic."""
    group = await get_group(session, group_id)
    if group.is_dynamic:
        return await data_access.list_contact_ids_matching_filter(
            session, filter_json=group.filter_json
        )
    return await data_access.list_static_member_contact_ids(
        session, group_id
    )


async def preview_audience_size(
    session: AsyncSession,
    *,
    filter_json: Optional[GroupFilter] = None,
    group_id: Optional[uuid.UUID] = None,
) -> int:
    """Count the contacts a filter or saved group would resolve to.
    Powers the "82 contacts will receive this" line in the Step 3.5.9
    audience builder — never returns rows, so it's cheap to call
    on every keystroke (with client-side debouncing)."""
    if (filter_json is None) == (group_id is None):
        # Schema validator catches this upstream; defensive guard here
        # for direct callers (tests, future scripts).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of `filter_json` or `group_id`.",
        )
    if filter_json is not None:
        return await data_access.count_contacts_matching_filter(
            session, filter_json=filter_json.model_dump(exclude_none=True)
        )

    # group_id path — delegate to resolver to honour static/dynamic mode.
    contact_ids = await resolve_group_contacts(session, group_id=group_id)
    return len(contact_ids)


async def get_member_count(
    session: AsyncSession, *, group: ContactGroup
) -> int:
    """Cheap COUNT used by list endpoints to attach `member_count` to
    each row. For dynamic groups this re-runs the filter — fine for
    the moderate list sizes we expect; if a tenant accumulates 100s
    of groups, the UI can switch to a lazy-load pattern."""
    if group.is_dynamic:
        return await data_access.count_contacts_matching_filter(
            session, filter_json=group.filter_json
        )
    return await data_access.count_static_members(session, group.id)


async def get_sample_member_ids(
    session: AsyncSession,
    *,
    group: ContactGroup,
    limit: int = 10,
) -> list[uuid.UUID]:
    """First N contact IDs for the detail-page preview. Same sort key
    the full resolver uses, so the sample matches the head of the
    full list."""
    if group.is_dynamic:
        return await data_access.list_contact_ids_matching_filter_limited(
            session, filter_json=group.filter_json, limit=limit
        )
    return await data_access.list_static_member_contact_ids_limited(
        session, group.id, limit=limit
    )


__all__ = [
    "create_group",
    "delete_group",
    "get_group",
    "get_member_count",
    "get_sample_member_ids",
    "list_groups",
    "preview_audience_size",
    "resolve_group_contacts",
    "update_group",
]
