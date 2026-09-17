"""HTTP routes for `standard_field_overrides`.

Mounted under `/api/v1/standard-fields`. Management endpoints (list,
upsert, reset) require `settings.standard_fields.manage` — Owner +
Admin by default. The `{entity}/render` endpoint is open to any
authenticated user since every form modal calls it on open.

  GET    /standard-fields/                      → all overrides for the org      [manage]
  GET    /standard-fields/{entity}/             → overrides for one entity        [manage]
  PUT    /standard-fields/{entity}/{field_key}  → upsert one override             [manage]
  DELETE /standard-fields/{entity}/{field_key}  → reset to registry defaults      [manage]
  GET    /standard-fields/{entity}/render       → merged defaults + overrides     [any user]
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.standard_fields import registry as field_registry
from src.app.core.standard_fields.schemas import (
    StandardFieldEntitiesResponse,
    StandardFieldEntity,
    StandardFieldOverrideIn,
    StandardFieldOverrideListResponse,
    StandardFieldOverrideOut,
    StandardFieldRenderedListResponse,
)
from src.app.core.standard_fields.service import (
    list_for_entity,
    list_for_org,
    render_for_entity,
    reset,
    upsert,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/standard-fields", tags=["Standard Fields"])


_REQUIRE_MANAGE = require_permissions("settings.standard_fields.manage")


@router.get("/", response_model=StandardFieldOverrideListResponse)
async def list_overrides(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_REQUIRE_MANAGE),
) -> StandardFieldOverrideListResponse:
    rows, total = await list_for_org(db, org_id=user.org_id)
    return StandardFieldOverrideListResponse(
        items=[StandardFieldOverrideOut.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{entity}/", response_model=StandardFieldOverrideListResponse)
async def list_entity_overrides(
    entity: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_REQUIRE_MANAGE),
) -> StandardFieldOverrideListResponse:
    rows, total = await list_for_entity(db, org_id=user.org_id, entity=entity)
    return StandardFieldOverrideListResponse(
        items=[StandardFieldOverrideOut.model_validate(r) for r in rows],
        total=total,
    )


@router.put(
    "/{entity}/{field_key}",
    response_model=StandardFieldOverrideOut,
)
async def upsert_override(
    entity: str,
    field_key: str,
    payload: StandardFieldOverrideIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_REQUIRE_MANAGE),
) -> StandardFieldOverrideOut:
    row = await upsert(
        db,
        org_id=user.org_id,
        entity=entity,
        field_key=field_key,
        payload=payload,
        actor_id=user.legacy_uuid,
    )
    return StandardFieldOverrideOut.model_validate(row)


@router.delete(
    "/{entity}/{field_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_override(
    entity: str,
    field_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_REQUIRE_MANAGE),
) -> Response:
    await reset(db, org_id=user.org_id, entity=entity, field_key=field_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/entities", response_model=StandardFieldEntitiesResponse)
async def list_entities(
    source: str = Query(
        default="core",
        description=(
            "Filter to a registration source: ``core`` (default — Core "
            "CRM entities only) or ``pack:<name>`` for a specific "
            "vertical pack (e.g. ``pack:furniture``). Pack UIs pass "
            "their own source to see their subset; the Core Settings "
            "page uses the default and never sees pack entities."
        ),
    ),
    _user: User = Depends(get_current_user),
) -> StandardFieldEntitiesResponse:
    """Registered entities + their overridable-field counts.

    Read off the in-process registry — no DB round trip. Drives the
    Settings page's entity-selector dropdown. Open to any authenticated
    user since the data is just labels.
    """
    items = [
        StandardFieldEntity(
            entity=name,
            field_count=len(field_registry.list_for_entity(name)),
        )
        for name in field_registry.list_entities(source=source)
    ]
    return StandardFieldEntitiesResponse(items=items)


@router.get(
    "/{entity}/render",
    response_model=StandardFieldRenderedListResponse,
)
async def render_entity(
    entity: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StandardFieldRenderedListResponse:
    """Merged registry-defaults + caller-org overrides for `entity`.

    Open to any authenticated user — every form modal in the app calls
    this on open. Hidden fields are included with `is_hidden=true`; the
    client decides whether to render. 404 if `entity` is not in the
    registry.
    """
    items = await render_for_entity(db, org_id=user.org_id, entity=entity)
    return StandardFieldRenderedListResponse(entity=entity, items=items)
