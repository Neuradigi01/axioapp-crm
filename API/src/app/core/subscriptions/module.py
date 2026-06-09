"""Subscriptions module descriptor.

`menu_position=None` keeps this entry out of the user sidebar — the
public `/pricing` page is the marketing surface, not a logged-in user
tab. The Billing settings tab (Step 16) is registered separately
under the Settings module.

Permissions
-----------
Step 19 registers two keys via this descriptor:

  - ``billing.read``   — read the current subscription, usage,
    invoices. Reuses the existing key already granted to Owner
    (and Admin, via the legacy core/billing module).
  - ``billing.manage`` — change plan, change seats, cancel,
    checkout. NEW key, granted to Owner only via Step 19's
    role-template edit.

The legacy ``core/billing`` module (invoice-PDF surface, unrelated to
subscriptions) registers ``billing.write`` / ``billing.refund`` of its
own; deliberately not reused here so that surface stays orthogonal.
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
    permissions=["billing.read", "billing.manage"],
)
