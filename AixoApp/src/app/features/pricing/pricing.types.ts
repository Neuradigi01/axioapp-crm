/**
 * Wire types for `GET /api/v1/plans` and the curated card content.
 *
 * The card feature lists are MARKETING copy, NOT the full entitlement
 * registry. When `plans.yaml` adds a new flagship feature, update the
 * corresponding `cardFeatures` block in `pricing.page.ts` by hand.
 */

export type BillingCycle = 'monthly' | 'annual';

export interface PlanPricing {
  monthly_bundle_usd: number;
  annual_bundle_usd: number;
  included_seats: number;
  extra_seat_monthly_usd: number;
  extra_seat_annual_usd: number;
}

export interface Plan {
  code: string;
  name: string;
  display_order: number;
  is_public: boolean;
  trial_duration_days: number;
  pricing: PlanPricing;
  // `caps` and `features` are present on the wire but not consumed
  // here — the marketing page surfaces curated copy, not the raw
  // entitlement set.
  caps: Record<string, number>;
  features: Record<string, boolean>;
}

export interface PlansResponse {
  plans: Plan[];
  currency: string;
  annual_discount_pct: number;
}
