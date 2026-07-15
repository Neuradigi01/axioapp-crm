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
  monthly_bundle_inr: number;
  annual_bundle_inr: number;
  extra_seat_monthly_usd: number;
  extra_seat_annual_usd: number;
  extra_seat_monthly_inr: number;
  extra_seat_annual_inr: number;
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

/**
 * Wire shape of `GET /api/v1/plans` — the public plan catalogue used
 * by the upgrade modal (Step 17). Mirrors `Plan.serialize()` on the
 * backend; the modal only reads `code`, `name`, `pricing` and
 * implicit "is public" filtering done by the API.
 */
export interface PlanCatalogEntry {
  code: string;
  name: string;
  display_order: number;
  is_public: boolean;
  trial_duration_days: number;
  pricing: {
    monthly_bundle_usd: number;
    annual_bundle_usd: number;
    monthly_bundle_inr: number;
    annual_bundle_inr: number;
    included_seats: number;
    extra_seat_monthly_usd: number;
    extra_seat_annual_usd: number;
    extra_seat_monthly_inr: number;
    extra_seat_annual_inr: number;
  };
  caps: Record<string, number>;
  features: Record<string, boolean>;
}

export interface PlansResponse {
  plans: PlanCatalogEntry[];
  currency: string;
  annual_discount_pct: number;
}

/**
 * Request / response for `POST /api/v1/subscriptions/checkout`
 * (Step 12). The modal POSTs a `CheckoutRequest` and either
 * receives a `CheckoutResponse` to redirect into, or a 4xx with a
 * `{error, ...}` shape the modal renders inline.
 */
export interface CheckoutRequest {
  to_plan: string;
  billing_cycle: BillingCycle;
  seats: number;
  success_url?: string;
  cancel_url?: string;
}

export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

/**
 * Wire types for the seat-management endpoints (Step 9 backend) used
 * by the seat-management modal (Step 17.b).
 *
 * `outcome_if_committed` on the preview is the same enum as the
 * commit-time `outcome` so the frontend can use one switch.
 */

export type SeatChangeOutcome = 'no_change' | 'needs_payment' | 'scheduled';

export interface SeatPreview {
  from_seats: number;
  to_seats: number;
  delta: number;
  outcome_if_committed: SeatChangeOutcome;
  amount_due_usd: number;
  next_renewal_at: string;
  monthly_cost_after_change_usd: number | null;
  annual_cost_after_change_usd: number | null;
}

export interface SeatChangeNeedsPaymentResponse {
  outcome: 'needs_payment';
  checkout_url: string | null;
  checkout_session_id: string | null;
  preview: SeatPreview;
}

export interface SeatChangeScheduledResponse {
  outcome: 'scheduled';
  effective_at: string;
  from_seats: number;
  to_seats: number;
  refund_due_usd: number;
}

export interface SeatChangeNoChangeResponse {
  outcome: 'no_change';
}

export type SeatChangeResponse =
  | SeatChangeNeedsPaymentResponse
  | SeatChangeScheduledResponse
  | SeatChangeNoChangeResponse;

/**
 * Mirror of the backend's `InvoiceRead` schema (Step 13.c).
 *
 * `null` is the wire-side default for optional fields — Stripe does
 * not always supply `number` or `pdf_url` (e.g. drafts), and the
 * billing UI degrades gracefully when those are absent.
 */
export type InvoiceStatus = 'paid' | 'open' | 'void' | 'uncollectible' | 'draft';

export interface Invoice {
  id: string;
  stripe_invoice_id: string;
  number: string | null;
  status: InvoiceStatus;
  amount_due_cents: number;
  amount_paid_cents: number;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  hosted_invoice_url: string | null;
  pdf_url: string | null;
  paid_at: string | null;
  created_at: string;
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
