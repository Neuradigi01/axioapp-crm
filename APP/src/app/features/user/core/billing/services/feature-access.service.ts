import { Injectable, computed, inject } from '@angular/core';

import { SubscriptionStateService } from './subscription-state.service';

/** Plan codes in ascending tier order. Used as a stable index for the
 *  "does my plan grant this feature?" comparison.
 *
 *  Mirrors the `display_order` field in `plans.yaml`. When that file
 *  changes, this constant must be updated by hand — frontend gating
 *  is a UX concern; the backend's `Entitlements` (Step 3) remains the
 *  source of truth at runtime.
 */
export const PLAN_TIER_ORDER = ['trial', 'basic', 'standard', 'enterprise'] as const;

export type PlanCode = (typeof PLAN_TIER_ORDER)[number];

/** Feature key → minimum plan code that grants it.
 *
 *  Mirrors the `features:` block in `plans.yaml`. Adding a feature
 *  here without updating the YAML (or vice versa) drifts UI from
 *  runtime gating; the entitlement service still rejects writes
 *  server-side either way.
 */
export const FEATURE_REQUIRED_PLAN: Readonly<Record<string, PlanCode>> = {
  'contacts.read': 'basic',
  'contacts.write': 'basic',
  'leads.manual_entry': 'basic',
  'tasks.read': 'basic',
  'tasks.write': 'basic',
  'walkins.read': 'basic',
  'pipelines.read': 'basic',
  'automation.workflows': 'standard',
  'conversations.unified_inbox': 'standard',
  'integrations.whatsapp': 'standard',
  'integrations.email_imap_smtp': 'standard',
  'ads.google_webhook': 'standard',
  'ads.meta_webhook': 'standard',
  'calls.recording': 'standard',
  'campaigns.email': 'standard',
  'sso.saml': 'enterprise',
  'audit.full_log': 'enterprise',
  multi_branch: 'enterprise',
  white_label: 'enterprise',
};

const PLAN_LABELS: Readonly<Record<PlanCode, string>> = {
  trial: 'Trial',
  basic: 'Basic',
  standard: 'Standard',
  enterprise: 'Enterprise',
};

function tierIndex(plan: string): number {
  return PLAN_TIER_ORDER.indexOf(plan as PlanCode);
}

/**
 * Lookup utilities for the locked-feature surfaces (Step 18).
 *
 * Stateless wrapper around `SubscriptionStateService` (Step 15) that
 * answers two questions:
 *
 *   1. Does the org's *current* plan grant feature key X?
 *   2. What's the cheapest plan that DOES grant feature key X?
 *
 * Trial is treated as Basic for feature purposes — matches the
 * backend (`plans.yaml`'s trial mirrors Basic features), so a
 * trialing user sees the same "locked" tiles a Basic-paid user does.
 */
@Injectable({ providedIn: 'root' })
export class FeatureAccessService {
  private readonly subscriptionState = inject(SubscriptionStateService);

  /** Plan currently active for the org. `null` while the subscription
   *  is still loading; consumers should render nothing in that frame
   *  to avoid a "Locked → Unlocked" flicker on first paint. */
  readonly currentPlan = computed<PlanCode | null>(() => {
    const code = this.subscriptionState.current()?.plan.code;
    if (code === undefined) return null;
    return PLAN_TIER_ORDER.includes(code as PlanCode) ? (code as PlanCode) : null;
  });

  /** True iff the current plan tier is >= the minimum tier that
   *  grants `featureKey`. Returns `false` for unknown features so a
   *  typo doesn't silently unlock content. */
  hasFeature(featureKey: string): boolean {
    const currentPlan = this.currentPlan();
    if (currentPlan === null) return false;
    const required = this.requiredPlanFor(featureKey);
    if (required === null) return false;
    return tierIndex(currentPlan) >= tierIndex(required);
  }

  /** Minimum plan code that grants `featureKey`, or `null` if the
   *  feature key is unknown to the registry. */
  requiredPlanFor(featureKey: string): PlanCode | null {
    const required = FEATURE_REQUIRED_PLAN[featureKey];
    return required ?? null;
  }

  /** Human label for the upgrade CTA. */
  labelFor(plan: PlanCode): string {
    return PLAN_LABELS[plan];
  }
}
