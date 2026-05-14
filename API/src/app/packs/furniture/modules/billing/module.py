"""Furniture-pack: Billing & POS module descriptor.

Permissions `pos.use` + `pos.refund` are pack-side (the core engine
already registers `billing.read/write/refund`). The sidebar entry
points at the frontend POS route (built in Step 4.12).
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="fp_billing",
    name="Billing & POS",
    icon="receipt",
    layer="pack",
    route="/api/v1/pos",
    frontend_route="/user/billing",
    menu_position=50,
    permissions=[
        "pos.use",
        "pos.refund",
    ],
)
