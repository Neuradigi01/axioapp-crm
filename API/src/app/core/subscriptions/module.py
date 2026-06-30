"""Subscriptions module descriptor.

Surfaces the SaaS Billing page (plans / seats / invoices / Stripe
checkout) as a top-level sidebar entry, mounted at `/user/subscription`
and gated to roles holding ``billing.manage`` — Owner-only by default.

Manager spec 2026-06-11 promoted this from a tab inside Settings to a
dedicated module; `menu_position=950` places it directly above
Settings (999) so the sidebar groups the two account-administration
surfaces together.

Permissions
-----------
  - ``billing.read``   — read the current subscription, usage,
    invoices. Granted to Owner (and Admin, via the legacy core/billing
    module).
  - ``billing.manage`` — change plan, change seats, cancel, checkout.
    Granted to Owner only via the role-template seed; controls both
    sidebar visibility (this descriptor) and the route guards.

The legacy ``core/billing`` module (invoice-PDF surface, unrelated to
subscriptions) registers ``billing.write`` / ``billing.refund`` of its
own; deliberately not reused here so that surface stays orthogonal.
The furniture pack's POS module (``fp_billing``) owns `/user/billing`
and is unrelated to SaaS subscription management.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="subscriptions",
    name="Billing",
    icon="credit-card",
    layer="core",
    route="/api/v1/plans",
    frontend_route="/user/subscription",
    menu_position=950,
    permissions=["billing.read", "billing.manage"],
)
