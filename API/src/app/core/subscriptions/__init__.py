"""Subscription plans, entitlements, and SaaS-billing surface.

NOT to be confused with `core/billing/`, which is the customer-facing
invoicing module (drafts, payments, refunds) that a tenant uses to
bill their own customers. This module is about how WE bill the tenant
for using the platform.

Step 1 exposes the plan registry over a public `/plans` API.
Later steps add the per-org subscription state, entitlement checks,
Stripe integration, and the in-app billing UI surface.
"""
from src.app.core.subscriptions.decorators import (
    CapCountProvider,
    enforces_cap,
    requires_feature,
)
from src.app.core.subscriptions.entitlements import (
    Entitlements,
    load_for_org,
    require_capacity,
    require_feature,
)
from src.app.core.subscriptions.exceptions import (
    EntitlementError,
    EntitlementReason,
)
from src.app.core.subscriptions.plans import (
    Cap,
    Plan,
    PlanCaps,
    PlanFeatures,
    PlanPricing,
    PlanRegistry,
    KNOWN_FEATURE_KEYS,
    UNLIMITED_SENTINEL,
)

__all__ = [
    "Cap",
    "CapCountProvider",
    "Entitlements",
    "EntitlementError",
    "EntitlementReason",
    "Plan",
    "PlanCaps",
    "PlanFeatures",
    "PlanPricing",
    "PlanRegistry",
    "KNOWN_FEATURE_KEYS",
    "UNLIMITED_SENTINEL",
    "enforces_cap",
    "load_for_org",
    "require_capacity",
    "require_feature",
    "requires_feature",
]
