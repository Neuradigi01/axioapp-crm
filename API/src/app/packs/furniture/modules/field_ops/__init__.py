"""Furniture-pack: field-ops module.

Third Layer-2 (pack) module. Reuses the core appointments engine for
scheduling and the custom-orders module for measurement copyback.

No `register_pipeline_table` call — field visits don't carry a
pipeline_stage column; they transition through the standard
appointment status enum (scheduled → completed) plus a per-visit
`completed_at` timestamp.

Standard-field overrides: the pack registers its `field_visit` entity
with the `core.standard_fields` registry so the Settings page's
"Standard Fields" tab can offer per-org label/required/visibility
overrides on the schedule-visit modal.
"""
from src.app.core.standard_fields import (
    StandardFieldDef,
    register as register_standard_field,
)
from src.app.packs.furniture.modules.field_ops.service import (
    add_photo,
    complete_visit,
    create_visit,
    delete_visit,
    get_visit,
    list_photos,
    list_visits,
    update_visit,
)


_BASIC_TEXT_PROPS = frozenset(
    {"label", "placeholder", "help", "required", "hidden", "display_order"}
)
_LOCKED_REQUIRED_PROPS = frozenset(
    {"label", "placeholder", "help", "display_order"}
)


def _register_field_visit_fields() -> None:
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="title",
            field_type="text",
            default_label="Title",
            default_placeholder="e.g. Measurement at customer site",
            default_help=None,
            default_required=True,
            default_min=None,
            default_max=255.0,
            default_step=None,
            default_display_order=0,
            backend_required=True,
            backend_validators=("max 255 chars",),
            overridable_props=_LOCKED_REQUIRED_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="purpose",
            field_type="select",
            default_label="Purpose",
            default_placeholder=None,
            default_help=None,
            default_required=False,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=1,
            backend_required=False,
            backend_validators=("one of: measurement, installation, inspection",),
            overridable_props=frozenset(
                {"label", "help", "required", "hidden", "display_order"}
            ),
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="scheduled_date",
            field_type="date",
            default_label="Date",
            default_placeholder=None,
            default_help=None,
            default_required=True,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=2,
            backend_required=True,
            backend_validators=("ISO-8601 date",),
            overridable_props=_LOCKED_REQUIRED_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="scheduled_time",
            field_type="text",
            default_label="Time",
            default_placeholder=None,
            default_help=None,
            default_required=True,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=3,
            backend_required=True,
            backend_validators=("HH:MM",),
            overridable_props=_LOCKED_REQUIRED_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="duration_min",
            field_type="number",
            default_label="Duration (min)",
            default_placeholder=None,
            default_help=None,
            default_required=True,
            default_min=15.0,
            default_max=1440.0,
            default_step=15.0,
            default_display_order=4,
            backend_required=True,
            backend_validators=("between 15 and 1440 minutes",),
            overridable_props=frozenset(
                {"label", "placeholder", "help", "min", "max", "step", "display_order"}
            ),
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="assigned_to_id",
            field_type="select",
            default_label="Assigned to",
            default_placeholder=None,
            default_help=None,
            default_required=True,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=5,
            backend_required=True,
            backend_validators=("must be an active staff member",),
            overridable_props=frozenset(
                {"label", "help", "display_order"}
            ),
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="location",
            field_type="text",
            default_label="Location",
            default_placeholder="Customer home / site address",
            default_help=None,
            default_required=False,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=6,
            backend_required=False,
            backend_validators=(),
            overridable_props=_BASIC_TEXT_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="field_visit",
            field_key="notes",
            field_type="textarea",
            default_label="Notes",
            default_placeholder="bring laser measure, special access instructions, …",
            default_help=None,
            default_required=False,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=7,
            backend_required=False,
            backend_validators=(),
            overridable_props=_BASIC_TEXT_PROPS,
        )
    )


_register_field_visit_fields()


__all__ = [
    "add_photo",
    "complete_visit",
    "create_visit",
    "delete_visit",
    "get_visit",
    "list_photos",
    "list_visits",
    "update_visit",
]
