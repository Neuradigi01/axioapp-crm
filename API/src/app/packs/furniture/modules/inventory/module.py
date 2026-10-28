"""Furniture-pack: Inventory module descriptor.

Auto-discovered at startup by the module registry walker — no core
changes required (rule 5). Lives at the conventional path
`src.app.packs.<pack>.modules.<module>.module` that the walker
searches.

`layer='pack'` marks this as a Layer-2 module (not core). The
frontend's sidebar component reads this and can render pack entries
under a separate section if desired.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="inventory",
    name="Inventory & Warehouse",
    icon="warehouse",
    layer="pack",
    route="/api/v1/inventory",
    frontend_route="/user/inventory",
    # `menu_position=20` slots Inventory near the top of the sidebar,
    # right after Dashboard. Other furniture pack modules (custom_orders,
    # field_ops, …) will pick adjacent positions in their own steps.
    menu_position=20,
    permissions=[
        "inventory.read",
        "inventory.write",
        "inventory.dispatch",
        "inventory.transfer",
    ],
)
