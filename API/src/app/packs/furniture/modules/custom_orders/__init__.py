"""Furniture-pack: custom-orders module.

Second Layer-2 (pack) module to touch the database. All tables are
`fp_*` prefixed.

Importing this module registers `fp_custom_orders` as a
pipeline-tracked card table with the core pipelines engine — that's
the allowlist `pipelines.move_card` consults before issuing a raw
UPDATE.

Standard-field overrides: the pack registers its `custom_order` entity
with the `core.standard_fields` registry so the Settings page's
"Standard Fields" tab can offer per-org label/required/visibility
overrides on the basics step of the create wizard.
"""

from src.app.core.pipelines.service import register_pipeline_table
from src.app.core.standard_fields import (
    StandardFieldDef,
)
from src.app.core.standard_fields import (
    register as register_standard_field,
)
from src.app.packs.furniture.modules.custom_orders.service import (
    add_measurement,
    add_photo,
    create_order,
    delete_order,
    get_order,
    list_measurements,
    list_orders,
    list_photos,
    list_stage_history,
    move_stage,
    update_order,
)

register_pipeline_table("fp_custom_orders")


# Standard-field overrides for the custom-order create/edit wizard's
# basics step. Title is backend-required (NOT NULL). Currency knobs
# carry full numeric override support.
_TEXT_PROPS = frozenset({"label", "placeholder", "help", "required", "hidden", "display_order"})
_LOCKED_REQUIRED_PROPS = frozenset({"label", "placeholder", "help", "display_order"})
_CURRENCY_PROPS = frozenset(
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


def _register_custom_order_fields() -> None:
    register_standard_field(
        StandardFieldDef(
            entity="custom_order",
            field_key="title",
            field_type="text",
            default_label="Title",
            default_placeholder="e.g. Custom wardrobe for Mr. Kumar",
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
            entity="custom_order",
            field_key="requirement",
            field_type="textarea",
            default_label="Special requirements",
            default_placeholder=None,
            default_help=None,
            default_required=False,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=1,
            backend_required=False,
            backend_validators=(),
            overridable_props=_TEXT_PROPS,
        )
    )
    for idx, (key, label) in enumerate(
        [
            ("material_primary", "Primary material"),
            ("material_secondary", "Secondary material"),
            ("color", "Color"),
            ("finish", "Finish"),
        ],
        start=2,
    ):
        register_standard_field(
            StandardFieldDef(
                entity="custom_order",
                field_key=key,
                field_type="text",
                default_label=label,
                default_placeholder=None,
                default_help=None,
                default_required=False,
                default_min=None,
                default_max=None,
                default_step=None,
                default_display_order=idx,
                backend_required=False,
                backend_validators=(),
                overridable_props=_TEXT_PROPS,
            )
        )
    register_standard_field(
        StandardFieldDef(
            entity="custom_order",
            field_key="total_amount",
            field_type="currency",
            default_label="Total (₹)",
            default_placeholder="0.00",
            default_help=None,
            default_required=False,
            default_min=0.0,
            default_max=None,
            default_step=0.01,
            default_display_order=6,
            backend_required=False,
            backend_validators=("must be ≥ 0",),
            overridable_props=_CURRENCY_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="custom_order",
            field_key="advance_paid",
            field_type="currency",
            default_label="Advance (₹)",
            default_placeholder="0.00",
            default_help=None,
            default_required=False,
            default_min=0.0,
            default_max=None,
            default_step=0.01,
            default_display_order=7,
            backend_required=False,
            backend_validators=("must be ≥ 0",),
            overridable_props=_CURRENCY_PROPS,
        )
    )
    register_standard_field(
        StandardFieldDef(
            entity="custom_order",
            field_key="expected_delivery_date",
            field_type="date",
            default_label="Expected delivery",
            default_placeholder=None,
            default_help=None,
            default_required=False,
            default_min=None,
            default_max=None,
            default_step=None,
            default_display_order=8,
            backend_required=False,
            backend_validators=(),
            overridable_props=frozenset(
                {"label", "placeholder", "help", "required", "hidden", "display_order"}
            ),
        )
    )


_register_custom_order_fields()


__all__ = [
    "add_measurement",
    "add_photo",
    "create_order",
    "delete_order",
    "get_order",
    "list_measurements",
    "list_orders",
    "list_photos",
    "list_stage_history",
    "move_stage",
    "update_order",
]
