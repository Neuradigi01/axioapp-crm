"""Save-target picker source for Ask-* and Set-Custom-Field nodes.

Merges two layers:

  * **Standard fields** — :mod:`core.standard_fields.registry` filtered
    by ``bot_writable=True``. Code-defined per Rule 6 pattern; adding a
    new bot-writable standard field is a one-line change on the
    registry, no migration.
  * **Custom fields** — every ``tbl_custom_field_definitions`` row for
    the org+entity. Operators create these ad-hoc from the CRM's Custom
    Fields settings UI.

Two entry points:

  * :func:`list_save_targets` — returns the picker payload the
    frontend Ask-* node editor consumes (Step 14). Grouped by entity
    for a nice dropdown UX.
  * :func:`validate_save_target` — parses ``"contact.first_name"`` or
    ``"contact.custom.foo"`` and confirms the target is safe to write
    to. Called by :mod:`service` on save + by the runtime handler
    before it writes anything.

The custom-field key regex ``^[a-z0-9_]{1,40}$`` and the
system-column collision guard live here — enforced at *both* save
time and runtime so a UI bypass or a mid-flight custom-field rename
can never sneak a write into a sensitive column.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as dal
from src.app.core.chatbots.exceptions import InvalidSaveTarget
from src.app.core.standard_fields import registry as sf_registry

# Custom-field keys are constrained so JSONB path resolution can't be
# tricked by an operator crafting a key like `../role` or a Postgres
# operator character. Also caps length so the picker UI can render
# cleanly.
_CUSTOM_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")

# System columns per entity that MUST NOT be written by a bot even
# via a custom-field name collision. Redundant with the registry's
# `bot_writable=False` on standard fields, but this guards against
# an operator creating a custom field literally named `role` or
# `owner_id` and the picker being tricked into surfacing it.
_SYSTEM_COLUMN_BLOCKLIST: dict[str, frozenset[str]] = {
    "contact": frozenset(
        {
            "id",
            "org_id",
            "assigned_to_id",
            "anonymised_at",
            "is_placeholder",
            "email_opt_in_status",
            "email_opt_out",
            "whatsapp_opt_in_status",
            "whatsapp_opt_out_reason",
            "created_at",
            "updated_at",
        }
    ),
    "lead": frozenset(
        {
            "id",
            "org_id",
            "owner_id",
            "assigned_to_id",
            "created_by_user_id",
            "created_at",
            "updated_at",
        }
    ),
    "walk_in": frozenset(
        {
            "id",
            "org_id",
            "assigned_to_id",
            "created_by_user_id",
            "created_at",
            "updated_at",
        }
    ),
}

# Entities the picker knows about. Constrained to those where a
# save-to registry entry actually makes sense — Ask-* nodes save to
# contact / lead / walk_in fields, not to invoice or catalog_item.
_SUPPORTED_ENTITIES: frozenset[str] = frozenset({"contact", "lead", "walk_in"})


@dataclass(frozen=True, slots=True)
class SaveTarget:
    """One entry in the picker. ``qualified_key`` is what the frontend
    sends back as ``save_to`` (e.g. ``"contact.first_name"`` or
    ``"contact.custom.membership_tier"``)."""

    entity: str
    field_key: str
    display_label: str
    format: str
    is_custom: bool
    qualified_key: str


async def list_save_targets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
) -> list[SaveTarget]:
    """Return the picker payload for one entity in one org. Standard
    bot-writable fields first, then custom fields ordered by
    ``display_order``.

    Raises :class:`InvalidSaveTarget` if the entity isn't supported.
    """
    if entity not in _SUPPORTED_ENTITIES:
        raise InvalidSaveTarget(
            f"entity '{entity}' has no save-to picker; supported: "
            f"{sorted(_SUPPORTED_ENTITIES)}"
        )

    out: list[SaveTarget] = []

    for std in sf_registry.list_bot_writable(entity):
        out.append(
            SaveTarget(
                entity=entity,
                field_key=std.field_key,
                display_label=std.default_label,
                format=std.field_type,
                is_custom=False,
                qualified_key=f"{entity}.{std.field_key}",
            )
        )

    custom_rows = await dal.list_visible_custom_fields_for_org(
        session,
        org_id=org_id,
        entity_type=entity,
    )
    for cf in custom_rows:
        if not _CUSTOM_KEY_RE.match(cf.field_key):
            # Legacy custom field with a key that predates the regex.
            # Silently skip from the picker — the operator can rename
            # it in the Custom Fields settings UI to make it available.
            continue
        blocklist = _SYSTEM_COLUMN_BLOCKLIST.get(entity, frozenset())
        if cf.field_key in blocklist:
            continue
        out.append(
            SaveTarget(
                entity=entity,
                field_key=cf.field_key,
                display_label=cf.field_label,
                format=cf.field_type.value if hasattr(cf.field_type, "value") else str(cf.field_type),
                is_custom=True,
                qualified_key=f"{entity}.custom.{cf.field_key}",
            )
        )

    return out


async def validate_save_target(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    qualified_key: str,
) -> SaveTarget:
    """Parse ``"contact.first_name"`` or ``"contact.custom.foo"`` and
    confirm the target is safe. Raises :class:`InvalidSaveTarget`
    on any bad shape.

    Guards:

      * Entity supported.
      * Custom-field key matches ``^[a-z0-9_]{1,40}$``.
      * Custom-field key does not collide with a system column.
      * Standard fields are ``bot_writable=True``.
      * Custom field row actually exists in this org.
    """
    parts = qualified_key.split(".")
    if len(parts) == 2:
        entity, key = parts
        is_custom = False
    elif len(parts) == 3 and parts[1] == "custom":
        entity, _, key = parts
        is_custom = True
    else:
        raise InvalidSaveTarget(
            f"save_to '{qualified_key}' must be '<entity>.<field>' or "
            f"'<entity>.custom.<field>'"
        )

    if entity not in _SUPPORTED_ENTITIES:
        raise InvalidSaveTarget(
            f"entity '{entity}' not supported for save_to"
        )

    if is_custom:
        if not _CUSTOM_KEY_RE.match(key):
            raise InvalidSaveTarget(
                f"custom field key '{key}' must match ^[a-z0-9_]{{1,40}}$"
            )
        blocklist = _SYSTEM_COLUMN_BLOCKLIST.get(entity, frozenset())
        if key in blocklist:
            raise InvalidSaveTarget(
                f"custom field key '{key}' collides with a system column on {entity}"
            )
        cf = await dal.get_custom_field_by_key(
            session,
            org_id=org_id,
            entity_type=entity,
            field_key=key,
        )
        if cf is None:
            raise InvalidSaveTarget(
                f"custom field '{entity}.custom.{key}' not defined in org"
            )
        return SaveTarget(
            entity=entity,
            field_key=key,
            display_label=cf.field_label,
            format=cf.field_type.value if hasattr(cf.field_type, "value") else str(cf.field_type),
            is_custom=True,
            qualified_key=qualified_key,
        )

    std = sf_registry.get(entity, key)
    if std is None or not std.bot_writable:
        raise InvalidSaveTarget(
            f"'{qualified_key}' is not bot-writable (either doesn't exist or "
            f"the field is not marked bot_writable=True in the registry)"
        )
    return SaveTarget(
        entity=entity,
        field_key=std.field_key,
        display_label=std.default_label,
        format=std.field_type,
        is_custom=False,
        qualified_key=qualified_key,
    )


def collect_save_targets_from_graph(graph: dict[str, Any]) -> list[str]:
    """Walk a graph payload and return every ``config.save_to`` value
    found on Ask-* / Set-Custom-Field nodes. The service calls
    :func:`validate_save_target` on each before persisting.

    Returned strings are as-typed by the frontend — validation
    normalises + fails on bad shapes downstream.
    """
    targets: list[str] = []
    for n in graph.get("nodes", []):
        node_type = n.get("type")
        if node_type not in {
            "ask_question",
            "ask_address",
            "ask_location",
            "ask_media",
            "set_custom_field",
        }:
            continue
        cfg = n.get("config") or {}
        raw = cfg.get("save_to")
        if isinstance(raw, str) and raw.strip():
            targets.append(raw.strip())
    return targets
