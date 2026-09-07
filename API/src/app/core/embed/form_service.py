"""Multi-form CRUD service for the embed module.

Every org may own many lead-capture forms — one per use case
(Contact Us, Quote Request, Newsletter, etc.). Each form is a row
in ``tbl_widget_configs`` with its own name, slug, JSONB config
document, and one-to-many embed keys.

This service is the ONLY layer that mutates form rows outside of the
legacy default-form path in :mod:`config_service`. It owns:

  * slug generation + de-duplication against existing live forms,
  * the "exactly one default per org" invariant (atomic swap),
  * config-document merge / re-validation on update (delegates to
    the existing validator in :mod:`config_service`),
  * soft-delete gating (the default form can't be deleted — set a
    new default first),
  * audit-log emissions.

Convention: this module OWNS transactions (commit / rollback /
refresh). The DAL never commits — it stages statements and returns.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.embed import data_access as _da
from src.app.core.embed.config_service import (
    _default_document,
    validate_custom_field_refs,
)
from src.app.core.embed.models import WidgetConfig
from src.app.core.embed.schemas import (
    WidgetConfigDocument,
    WidgetFormCreate,
    WidgetFormUpdate,
)
from src.app.shared.audit import log_entity_change

# --- Slug helpers ----------------------------------------------------------

# Column limit is 64 chars — leave 6 for a "-<n>" dedupe suffix so a long
# name doesn't force the deduper to truncate the base slug.
_SLUG_BASE_MAX = 58
_SLUG_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_RE_MULTI_DASH = re.compile(r"-+")


def _slugify(name: str) -> str:
    """Lowercase, non-alnum → ``-``, collapse repeats, trim edges.

    Returns ``'form'`` as a fallback when the name is entirely
    non-alphanumeric (e.g. an emoji-only display name) — nothing
    else on the app produces an empty slug and the DB NOT NULL
    would reject one anyway.
    """
    slug = _SLUG_RE_NON_ALNUM.sub("-", name.lower())
    slug = _SLUG_RE_MULTI_DASH.sub("-", slug).strip("-")
    if not slug:
        return "form"
    return slug[:_SLUG_BASE_MAX]


async def _resolve_unique_slug(
    session: AsyncSession, *, org_id: uuid.UUID, base: str
) -> str:
    """Return ``base`` if free, else ``base-2``, ``base-3``, … until we
    find a slug not in use by any LIVE form on the org. One DB read;
    dedupe loop is pure Python.
    """
    taken = await _da.existing_form_slugs_for_org(session, org_id)
    if base not in taken:
        return base
    n = 2
    while True:
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
        n += 1


# --- List / get -----------------------------------------------------------


async def list_forms(session: AsyncSession, *, org_id: uuid.UUID) -> list[tuple[WidgetConfig, int]]:
    """Every live form for the org, paired with its live-key count.

    Returns ``[(form, key_count), ...]`` in the DAL's default order
    (default first, then alphabetical). Router projects into
    :class:`WidgetFormListItem`.
    """
    forms = await _da.list_widget_forms_for_org(session, org_id)
    if not forms:
        return []
    counts = await _da.count_live_keys_per_form(session, org_id=org_id)
    return [(f, counts.get(f.id, 0)) for f in forms]


async def get_form(session: AsyncSession, *, form_id: uuid.UUID) -> WidgetConfig:
    """Single form by id. 404 on unknown id OR soft-deleted row."""
    form = await _da.get_widget_form_by_id(session, form_id)
    if form is None or form.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="form not found"
        )
    return form


# --- Create ---------------------------------------------------------------


async def create_form(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    payload: WidgetFormCreate,
) -> WidgetConfig:
    """Insert a new form for the org. Never marked default — the org's
    default only moves via the dedicated set-default endpoint.

    Slug resolution:
      * caller-supplied ``slug`` — used as-is if free, 409 if taken.
      * no ``slug`` — derived from ``name`` via :func:`_slugify` and
        deduped against existing live slugs (``contact-us`` →
        ``contact-us-2``).
    """
    if payload.slug is not None:
        taken = await _da.existing_form_slugs_for_org(session, org_id)
        if payload.slug in taken:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Slug {payload.slug!r} is already used by another "
                    "form on this org — pick a different slug or leave "
                    "it blank to auto-generate."
                ),
            )
        slug = payload.slug
    else:
        slug = await _resolve_unique_slug(
            session, org_id=org_id, base=_slugify(payload.name)
        )

    form = WidgetConfig(
        org_id=org_id,
        name=payload.name,
        slug=slug,
        is_default=False,
        config=_default_document().model_dump(mode="json"),
        updated_by=actor_id,
    )
    _da.insert_widget_form(session, form)
    await session.commit()
    await session.refresh(form)

    await log_entity_change(
        action="embed.form.created",
        entity_type="widget_form",
        entity_id=form.id,
        after={
            "form_id": str(form.id),
            "name": form.name,
            "slug": form.slug,
        },
    )
    return form


# --- Update ---------------------------------------------------------------


async def update_form(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    form_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    payload: WidgetFormUpdate,
) -> WidgetConfig:
    """Patch-style update. Every supplied field is applied; omitted
    fields stay as they are. The config sub-patch, when supplied, is
    merged into the existing document then re-validated (custom-field
    refs, select-field options, etc.) exactly like the legacy
    :func:`config_service.update` path.
    """
    form = await get_form(session, form_id=form_id)

    if payload.name is not None:
        form.name = payload.name

    if payload.slug is not None and payload.slug != form.slug:
        taken = await _da.existing_form_slugs_for_org(session, org_id)
        # The form's own current slug is in ``taken`` — exclude it so
        # a no-op slug re-submit doesn't 409 against itself. (Guarded
        # by the != check above but belt-and-suspenders.)
        taken.discard(form.slug)
        if payload.slug in taken:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Slug {payload.slug!r} is already used by another "
                    "form on this org."
                ),
            )
        form.slug = payload.slug

    if payload.config is not None:
        current = WidgetConfigDocument.model_validate(form.config)
        patch = payload.config.model_dump(exclude_unset=True, exclude_none=False)
        merged_dict = current.model_dump(mode="json")
        for key, value in patch.items():
            merged_dict[key] = value
        merged = WidgetConfigDocument.model_validate(merged_dict)

        await validate_custom_field_refs(session, fields=merged.fields)
        form.config = merged.model_dump(mode="json")

    form.updated_by = actor_id
    await session.commit()
    await session.refresh(form)

    await log_entity_change(
        action="embed.form.updated",
        entity_type="widget_form",
        entity_id=form.id,
        after={
            "form_id": str(form.id),
            "name": form.name,
            "slug": form.slug,
        },
    )
    return form


# --- Set default ----------------------------------------------------------


async def set_default_form(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    form_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> WidgetConfig:
    """Atomically flip the org's default form to ``form_id``. The
    previous default is cleared in the same transaction so the
    "exactly one default per org" invariant is never violated.

    409 if the target form is soft-deleted (can't default to a
    retired form).
    """
    form = await get_form(session, form_id=form_id)
    if form.org_id != org_id:
        # Belt-and-suspenders: get_form auto-tenant-filters, but this
        # guards the raw id path against a cross-org submit if the
        # tenant listener is ever bypassed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="form not found"
        )
    if form.is_default:
        return form  # No-op, don't emit an audit row.

    await _da.swap_default_form(session, org_id=org_id, new_default_id=form_id)
    await session.commit()
    await session.refresh(form)

    await log_entity_change(
        action="embed.form.default_changed",
        entity_type="widget_form",
        entity_id=form.id,
        after={
            "form_id": str(form.id),
            "name": form.name,
        },
    )
    return form


# --- Soft-delete ----------------------------------------------------------


async def delete_form(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    form_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> None:
    """Soft-delete the form — stamps ``deleted_at`` so historical
    leads pointing at ``attribution.form_id`` still resolve a name.

    Blocked when the target is the org's default form. Callers must
    promote a different form to default first. Also blocked when the
    org has only one live form — an org must always have at least
    one form so any legacy embed keeps working.
    """
    form = await get_form(session, form_id=form_id)
    if form.is_default:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot delete the default form. Promote a different "
                "form to default first, then delete this one."
            ),
        )
    live = await _da.list_widget_forms_for_org(session, org_id)
    if len(live) <= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot delete the org's only form — every legacy embed "
                "snippet needs at least one live form to resolve to."
            ),
        )

    await _da.soft_delete_widget_form(
        session, form_id=form_id, deleted_at=datetime.now(UTC)
    )
    await session.commit()

    await log_entity_change(
        action="embed.form.deleted",
        entity_type="widget_form",
        entity_id=form_id,
        after={
            "form_id": str(form_id),
            "name": form.name,
        },
    )


__all__ = [
    "create_form",
    "delete_form",
    "get_form",
    "list_forms",
    "set_default_form",
    "update_form",
]
