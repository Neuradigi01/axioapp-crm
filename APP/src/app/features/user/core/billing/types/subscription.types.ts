/**
 * Wire types for `GET /api/v1/subscriptions/current` (Step 7's API).
 *
 * Mirrors `SubscriptionCurrentResponse` from the backend's
 * `core/subscriptions/schemas.py`. Trimmed to the fields the trial
 * banner (Step 15) and the billing settings page (Step 16) consume.
 */

export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'read_only'
  | 'archived'
  | 'cancelled';

export type BillingCycle = 'monthly' | 'annual';

export interface PlanShort {
  code: string;
  name: string;
  monthly_bundle_usd: number;
  annual_bundle_usd: number;
  extra_seat_monthly_usd: number;
  extra_seat_annual_usd: number;
  included_seats: number;
}

export interface TrialInfo {
  started_at: string;
  ends_at: string;
  /** Always clamped at 0 by the backend — see Step 7's `from_components`. */
  days_remaining: number;
}

export interface PeriodInfo {
  start: string;
  end: string;
  renews_at: string;
}

export interface SeatsInfo {
  included: number;
  purchased: number;
  in_use: number;
  extra_seat_cost_per_period_usd: number;
}

export interface UsageRow {
  resource: string;
  current: number;
  cap: number;
  is_unlimited: boolean;
}

export interface SubscriptionCurrent {
  id: string;
  plan: PlanShort;
  status: SubscriptionStatus;
  billing_cycle: BillingCycle;
  trial: TrialInfo | null;
  period: PeriodInfo;
  seats: SeatsInfo;
  usage: UsageRow[];
  read_only: boolean;
  archived: boolean;
  cancelled: boolean;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
}
