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
from src.app.core.subscriptions.lifecycle import (
    fire_due_reminders,
    scan_and_transition_due,
    transition_if_due,
)
from src.app.core.subscriptions.notifications import (
    BillingEmailKey,
    send_billing_email,
)
from src.app.core.subscriptions.signup_hook import (
    TRIAL_DURATION,
    TRIAL_SEATS,
    create_trial_subscription,
)
from src.app.core.subscriptions.usage_service import (
    RESOURCE_PERIOD_KIND,
    get as usage_get,
    increment as usage_increment,
    snapshot as usage_snapshot,
)

__all__ = [
    "BillingEmailKey",
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
    "RESOURCE_PERIOD_KIND",
    "TRIAL_DURATION",
    "TRIAL_SEATS",
    "UNLIMITED_SENTINEL",
    "create_trial_subscription",
    "enforces_cap",
    "fire_due_reminders",
    "load_for_org",
    "require_capacity",
    "require_feature",
    "requires_feature",
    "scan_and_transition_due",
    "send_billing_email",
    "transition_if_due",
    "usage_get",
    "usage_increment",
    "usage_snapshot",
]
