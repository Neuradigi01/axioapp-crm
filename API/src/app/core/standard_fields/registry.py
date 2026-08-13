"""Registry of overridable standard (DB-column) fields per entity.

Parallel surface to Custom Fields. Where `custom_fields` lets an org
*add* extra columns to an entity, this registry declares which of the
*canonical* columns on a form can have their label, required-ness,
visibility, and numeric bounds overridden per org.

The registry is **code-defined** (Rule 6 pattern — like `role_templates`
and `module_registry`). Per-org override **values** live in the
`standard_field_overrides` DB table created in Step 2.

`core/` registers core CRM entities (contact, lead, walk_in, task,
appointment, catalog_item). Packs register their own entities through
the same `register(...)` function — Rule 1 holds (`core/` never imports
`packs/`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldType = Literal[
    "text",
    "textarea",
    "email",
    "tel",
    "number",
    "currency",
    "date",
    "datetime",
    "select",
    "multiselect",
    "tags",
    "boolean",
]


_NUMERIC_TYPES: frozenset[str] = frozenset({"number", "currency"})

_VALID_PROPS: frozenset[str] = frozenset(
    {
        "label",
        "placeholder",
        "help",
        "required",
        "hidden",
        "min",
        "max",
        "step",
        "display_order",
    }
)

_NUMERIC_ONLY_PROPS: frozenset[str] = frozenset({"min", "max", "step"})


@dataclass(frozen=True, slots=True)
class StandardFieldDef:
    """One overridable standard field on one entity.

    `overridable_props` is the contract enforced at PUT time: a payload
    that tries to set a prop not in this set returns 422. `__post_init__`
    rejects illegal combinations at registration time so a developer
    catches the mistake on startup, not on the first API call.

    ``bot_writable`` (``tasks/chatbot-builder`` Step 2) gates whether
    an Ask-* / Set-Custom-Field chatbot node may write to this field.
    Default False so new fields are opt-in; sensitive columns
    (``role``, ``owner_id``, ``balance``, verification timestamps,
    ``pin_hash``) are never listed and therefore never bot-writable.
    """

    entity: str
    field_key: str
    field_type: FieldType
    default_label: str
    default_placeholder: str | None
    default_help: str | None
    default_required: bool
    default_min: float | None
    default_max: float | None
    default_step: float | None
    default_display_order: int
    backend_required: bool
    backend_validators: tuple[str, ...]
    overridable_props: frozenset[str]
    bot_writable: bool = False

    def __post_init__(self) -> None:
        if not self.entity or not self.entity.replace("_", "").isalnum():
            raise ValueError(f"entity {self.entity!r} must be snake_case alphanumeric")
        if not self.field_key or not self.field_key.replace("_", "").isalnum():
            raise ValueError(f"field_key {self.field_key!r} must be snake_case alphanumeric")

        unknown = self.overridable_props - _VALID_PROPS
        if unknown:
            raise ValueError(
                f"{self.entity}.{self.field_key}: unknown overridable_props {sorted(unknown)}"
            )

        if self.field_type not in _NUMERIC_TYPES:
            numeric_leak = self.overridable_props & _NUMERIC_ONLY_PROPS
            if numeric_leak:
                raise ValueError(
                    f"{self.entity}.{self.field_key}: {sorted(numeric_leak)} only valid "
                    f"on number/currency types, not {self.field_type!r}"
                )

        if self.backend_required:
            illegal = self.overridable_props & {"required", "hidden"}
            if illegal:
                raise ValueError(
                    f"{self.entity}.{self.field_key}: cannot expose {sorted(illegal)} "
                    f"when backend_required=True (would let the UI block creates)"
                )


_REGISTRY: dict[tuple[str, str], StandardFieldDef] = {}


def register(definition: StandardFieldDef) -> None:
    """Add a field to the registry. Duplicate `(entity, field_key)` raises."""
    key = (definition.entity, definition.field_key)
    if key in _REGISTRY:
        raise ValueError(
            f"standard field {definition.entity}.{definition.field_key} already registered"
        )
    _REGISTRY[key] = definition


def get(entity: str, field_key: str) -> StandardFieldDef | None:
    """Resolve one field, or `None` if not registered."""
    return _REGISTRY.get((entity, field_key))


def list_for_entity(entity: str) -> list[StandardFieldDef]:
    """All fields registered for `entity`, ordered by `default_display_order`."""
    return sorted(
        (d for (e, _), d in _REGISTRY.items() if e == entity),
        key=lambda d: (d.default_display_order, d.field_key),
    )


def list_all() -> list[StandardFieldDef]:
    """Every registered field across every entity."""
    return list(_REGISTRY.values())


def list_bot_writable(entity: str) -> list[StandardFieldDef]:
    """Registered standard fields for ``entity`` where
    ``bot_writable=True``. Consumed by
    :mod:`core.chatbots.save_target_registry` to build the Ask-* /
    Set-Custom-Field save-to picker.

    Ordered by ``default_display_order`` then ``field_key`` for
    stable dropdown UX.
    """
    return sorted(
        (
            d
            for (e, _), d in _REGISTRY.items()
            if e == entity and d.bot_writable
        ),
        key=lambda d: (d.default_display_order, d.field_key),
    )


def list_entities() -> list[str]:
    """Distinct entity names registered."""
    return sorted({e for (e, _) in _REGISTRY.keys()})


def get_overridable_props(entity: str, field_key: str) -> frozenset[str]:
    """Whitelist of override props for `(entity, field_key)`. Empty if unknown."""
    definition = _REGISTRY.get((entity, field_key))
    return definition.overridable_props if definition else frozenset()


def _clear_for_tests() -> None:
    """Wipe the registry. Tests only — production never calls this."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Core CRM seed registrations
#
# `overridable_props` columns:
#   "label", "placeholder", "help", "required", "hidden",
#   "min", "max", "step", "display_order"
#
# Locked combinations:
#   - backend_required=True   → "required"/"hidden" excluded (enforced by
#                               __post_init__; the UI would otherwise let
#                               an Owner block legitimate creates).
#   - non-numeric field_type  → "min"/"max"/"step" excluded.
#
# Defaults mirror the current hardcoded HTML in each modal so an org with
# no override rows sees today's behaviour byte-for-byte.
# ---------------------------------------------------------------------------


# --- Contacts -----------------------------------------------------------------

register(
    StandardFieldDef(
        entity="contact",
        field_key="full_name",
        field_type="text",
        default_label="Full name",
        default_placeholder="e.g. Asha Reddy",
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("max 255 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="contact",
        field_key="phone",
        field_type="tel",
        default_label="Phone",
        default_placeholder="+91 9000000001",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=32.0,
        default_step=None,
        default_display_order=1,
        backend_required=False,
        backend_validators=("max 32 chars",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="contact",
        field_key="email",
        field_type="email",
        default_label="Email",
        default_placeholder="asha@example.com",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=2,
        backend_required=False,
        backend_validators=("RFC 5322 email format", "max 255 chars"),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="contact",
        field_key="source",
        field_type="text",
        default_label="Source",
        default_placeholder="walk_in, referral, …",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=64.0,
        default_step=None,
        default_display_order=3,
        backend_required=False,
        backend_validators=("max 64 chars",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="contact",
        field_key="tags",
        field_type="tags",
        default_label="Tags",
        default_placeholder="lead, vip",
        default_help="Comma-separated.",
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=4,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset({"label", "placeholder", "help", "hidden", "display_order"}),
    )
)


# --- Leads --------------------------------------------------------------------

register(
    StandardFieldDef(
        entity="lead",
        field_key="pipeline_stage",
        field_type="select",
        default_label="Pipeline stage",
        default_placeholder=None,
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("must match a stage from the leads pipeline",),
        overridable_props=frozenset({"label", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="lead",
        field_key="budget",
        field_type="currency",
        default_label="Budget (₹)",
        default_placeholder="0.00",
        default_help=None,
        default_required=False,
        default_min=0.0,
        default_max=None,
        default_step=0.01,
        default_display_order=1,
        backend_required=False,
        backend_validators=("must be ≥ 0",),
        overridable_props=frozenset(
            {
                "label",
                "placeholder",
                "help",
                "required",
                "hidden",
                "min",
                "max",
                "step",
                "display_order",
            }
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="lead",
        field_key="expected_close_date",
        field_type="date",
        default_label="Expected close date",
        default_placeholder="dd-mm-yyyy",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=2,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)


# --- Walk-ins ----------------------------------------------------------------

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="phone",
        field_type="tel",
        default_label="Phone",
        default_placeholder="+91 9000000001",
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=32.0,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("max 32 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="full_name",
        field_type="text",
        default_label="Full name",
        default_placeholder="e.g. Asha Reddy",
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=1,
        backend_required=True,
        backend_validators=("max 255 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="email",
        field_type="email",
        default_label="Email",
        default_placeholder="asha@example.com",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=2,
        backend_required=False,
        backend_validators=("RFC 5322 email format",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="source",
        field_type="text",
        default_label="Source",
        default_placeholder="walk_in",
        default_help="Defaults to 'walk_in' on the reception desk.",
        default_required=False,
        default_min=None,
        default_max=64.0,
        default_step=None,
        default_display_order=3,
        backend_required=False,
        backend_validators=("max 64 chars",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="requirement",
        field_type="textarea",
        default_label="Requirement",
        default_placeholder="What they're shopping for…",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=4,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
        bot_writable=True,
    )
)

register(
    StandardFieldDef(
        entity="walk_in",
        field_key="budget",
        field_type="currency",
        default_label="Budget (₹)",
        default_placeholder="0.00",
        default_help=None,
        default_required=False,
        default_min=0.0,
        default_max=None,
        default_step=0.01,
        default_display_order=5,
        backend_required=False,
        backend_validators=("must be ≥ 0",),
        bot_writable=True,
        overridable_props=frozenset(
            {
                "label",
                "placeholder",
                "help",
                "required",
                "hidden",
                "min",
                "max",
                "step",
                "display_order",
            }
        ),
    )
)


# --- Tasks --------------------------------------------------------------------

register(
    StandardFieldDef(
        entity="task",
        field_key="title",
        field_type="text",
        default_label="Title",
        default_placeholder="Follow up with Asha…",
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("max 255 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="task",
        field_key="description",
        field_type="textarea",
        default_label="Description",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=1,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="task",
        field_key="due_at",
        field_type="datetime",
        default_label="Due",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=2,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="task",
        field_key="priority",
        field_type="select",
        default_label="Priority",
        default_placeholder=None,
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=3,
        backend_required=True,
        backend_validators=("must be one of: low, med, high",),
        overridable_props=frozenset({"label", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="task",
        field_key="assigned_to_id",
        field_type="select",
        default_label="Assignee",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=4,
        backend_required=False,
        backend_validators=("must be an active org member",),
        overridable_props=frozenset({"label", "help", "required", "hidden", "display_order"}),
    )
)


# --- Appointments -------------------------------------------------------------

register(
    StandardFieldDef(
        entity="appointment",
        field_key="title",
        field_type="text",
        default_label="Title",
        default_placeholder=None,
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("max 255 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="appointment",
        field_key="purpose",
        field_type="text",
        default_label="Purpose",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=1,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="appointment",
        field_key="scheduled_at",
        field_type="datetime",
        default_label="When",
        default_placeholder=None,
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=2,
        backend_required=True,
        backend_validators=("ISO-8601 datetime",),
        overridable_props=frozenset({"label", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="appointment",
        field_key="duration_min",
        field_type="number",
        default_label="Duration (minutes)",
        default_placeholder="60",
        default_help=None,
        default_required=True,
        default_min=1.0,
        default_max=1440.0,
        default_step=1.0,
        default_display_order=3,
        backend_required=True,
        backend_validators=("between 1 and 1440 minutes",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "min", "max", "step", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="appointment",
        field_key="location",
        field_type="text",
        default_label="Location",
        default_placeholder="Showroom, Bengaluru…",
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=4,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)


# --- Catalog items ------------------------------------------------------------

register(
    StandardFieldDef(
        entity="catalog_item",
        field_key="sku",
        field_type="text",
        default_label="SKU",
        default_placeholder=None,
        default_help="Stable identifier. Cannot be changed once created.",
        default_required=True,
        default_min=None,
        default_max=64.0,
        default_step=None,
        default_display_order=0,
        backend_required=True,
        backend_validators=("max 64 chars", "unique per org"),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="catalog_item",
        field_key="name",
        field_type="text",
        default_label="Name",
        default_placeholder=None,
        default_help=None,
        default_required=True,
        default_min=None,
        default_max=255.0,
        default_step=None,
        default_display_order=1,
        backend_required=True,
        backend_validators=("max 255 chars",),
        overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),
    )
)

register(
    StandardFieldDef(
        entity="catalog_item",
        field_key="category",
        field_type="text",
        default_label="Category",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=64.0,
        default_step=None,
        default_display_order=2,
        backend_required=False,
        backend_validators=("max 64 chars",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "required", "hidden", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="catalog_item",
        field_key="price",
        field_type="currency",
        default_label="Price (₹)",
        default_placeholder="0.00",
        default_help=None,
        default_required=True,
        default_min=0.0,
        default_max=None,
        default_step=0.01,
        default_display_order=3,
        backend_required=True,
        backend_validators=("must be ≥ 0",),
        overridable_props=frozenset(
            {"label", "placeholder", "help", "min", "max", "step", "display_order"}
        ),
    )
)

register(
    StandardFieldDef(
        entity="catalog_item",
        field_key="is_active",
        field_type="boolean",
        default_label="Active",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=4,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset({"label", "help", "hidden", "display_order"}),
    )
)
