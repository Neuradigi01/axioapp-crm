"""Subscriptions module descriptor.

`menu_position=None` keeps this entry out of the user sidebar — the
public `/pricing` page is the marketing surface, not a logged-in user
tab. The Billing settings tab (Step 16) is registered separately
under the Settings module.

`permissions=[]` because Step 1's endpoints are public. Later steps
(Step 19) introduce `subscriptions.read` / `subscriptions.manage`
keys, which are registered then via this same module descriptor.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="subscriptions",
    name="Subscriptions",
    icon="credit-card",
    layer="core",
    route="/api/v1/plans",
    frontend_route="/pricing",
    menu_position=None,
    permissions=[],
)
