"""Core billing module descriptor.

`menu_position=None` keeps this entry out of the sidebar — billing is
exposed in the UI via the furniture-pack's "Billing & POS" module
(menu_position 50). Core still registers the descriptor so the three
core billing permissions land in the `permissions` table at startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="billing",
    name="Billing",
    icon="receipt",
    layer="core",
    route="/api/v1/invoices",
    frontend_route="/user/billing",
    menu_position=None,
    permissions=[
        "billing.read",
        "billing.write",
        "billing.refund",
    ],
)
