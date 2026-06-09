import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';

import { BillingApiService } from '../../services/billing-api.service';
import { SubscriptionStateService } from '../../services/subscription-state.service';
import { UpgradeModalService } from '../../services/upgrade-modal.service';
import {
  BillingCycle,
  PlanCatalogEntry,
} from '../../types/subscription.types';

/** Plan code shown with the "Most popular" ribbon (matches the public
 *  `/pricing` page so messaging is consistent). */
const POPULAR_PLAN_CODE = 'standard';

/**
 * Upgrade modal — Step 17.a.
 *
 * Lifecycle:
 *   - Mounted globally in the shell. Renders nothing when
 *     `UpgradeModalService.state().open` is `false`.
 *   - On open, fetches the public plan catalogue (once per modal
 *     session — the list never changes mid-flight).
 *   - Pre-fills plan / cycle / seats from the service's open options,
 *     falling back to current subscription state when omitted.
 *   - "Continue to payment" POSTs `/subscriptions/checkout` and
 *     hard-redirects via `window.location.href` into Stripe Checkout.
 *   - Backend 4xx detail is rendered inline ("seats below in_use",
 *     "cannot change to trial", etc.) without closing the modal.
 */
@Component({
  selector: 'crm-upgrade-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './upgrade-modal.component.html',
  styleUrl: './upgrade-modal.component.css',
})
export class UpgradeModalComponent {
  private readonly modalState = inject(UpgradeModalService);
  private readonly subscriptionState = inject(SubscriptionStateService);
  private readonly api = inject(BillingApiService);

  /** True when the shell should mount the modal DOM. */
  protected readonly isOpen = computed(
    () => this.modalState.state().open,
  );

  // ---- Catalogue ---------------------------------------------------------

  protected readonly plans = signal<PlanCatalogEntry[]>([]);
  protected readonly plansLoading = signal<boolean>(false);
  protected readonly plansError = signal<boolean>(false);

  /** Plans visible in the modal — sorted by display_order ascending. */
  protected readonly visiblePlans = computed(() =>
    [...this.plans()].sort((a, b) => a.display_order - b.display_order),
  );

  // ---- Selections (signals driven by the open-event prefill) -------------

  protected readonly selectedPlan = signal<string | null>(null);
  protected readonly selectedCycle = signal<BillingCycle>('monthly');
  protected readonly selectedSeats = signal<number>(1);

  // ---- Submit lifecycle --------------------------------------------------

  protected readonly isSubmitting = signal<boolean>(false);
  protected readonly submitError = signal<string | null>(null);

  // ---- Derived view models -----------------------------------------------

  /** Resolves the catalogue entry currently selected. */
  protected readonly selectedPlanEntry = computed<PlanCatalogEntry | null>(
    () => this.plans().find((p) => p.code === this.selectedPlan()) ?? null,
  );

  /** Bundle floor for the selected plan; the seat counter clamps to it. */
  protected readonly minSeats = computed<number>(() => {
    const plan = this.selectedPlanEntry();
    if (plan === null) return 1;
    const inUse = this.subscriptionState.current()?.seats.in_use ?? 0;
    return Math.max(plan.pricing.included_seats, inUse);
  });

  /** Best-effort estimate matching Step 9's preview math — Stripe's
   *  proration may differ by a few cents (documented in the spec). */
  protected readonly estimateToday = computed<number>(() => {
    const plan = this.selectedPlanEntry();
    if (plan === null) return 0;
    const cycle = this.selectedCycle();
    const bundle =
      cycle === 'annual'
        ? plan.pricing.annual_bundle_usd
        : plan.pricing.monthly_bundle_usd;
    const extraSeatCost =
      cycle === 'annual'
        ? plan.pricing.extra_seat_annual_usd
        : plan.pricing.extra_seat_monthly_usd;
    const extras = Math.max(
      0,
      this.selectedSeats() - plan.pricing.included_seats,
    );
    return bundle + extras * extraSeatCost;
  });

  /** Per-cycle recurring cost shown under the estimate. */
  protected readonly renewalAmount = computed<number>(
    () => this.estimateToday(),
  );

  protected readonly cycleLabel = computed<string>(() =>
    this.selectedCycle() === 'annual' ? 'year' : 'month',
  );

  constructor() {
    // Fetch the catalogue lazily — the first open event triggers it,
    // subsequent opens reuse the cached list (the plan catalogue is
    // immutable during a session).
    effect(() => {
      const state = this.modalState.state();
      if (state.open && this.plans().length === 0 && !this.plansLoading()) {
        this.fetchPlans();
      }
    });

    // Reapply prefill defaults each time the modal opens — so a second
    // open from a different surface (banner vs settings card) honours
    // its own context.
    effect(() => {
      const state = this.modalState.state();
      if (!state.open) return;
      this.submitError.set(null);

      const sub = this.subscriptionState.current();
      const fallbackPlan = sub?.plan.code ?? POPULAR_PLAN_CODE;
      this.selectedPlan.set(state.initialPlan ?? fallbackPlan);

      const fallbackCycle: BillingCycle = sub?.billing_cycle ?? 'monthly';
      this.selectedCycle.set(state.initialCycle ?? fallbackCycle);

      const fallbackSeats =
        state.initialSeats ??
        Math.max(sub?.seats.purchased ?? 1, sub?.seats.in_use ?? 1);
      this.selectedSeats.set(fallbackSeats);
    });

    // Keep seat count above the bundle floor as the user switches
    // plans — otherwise picking Basic after starting on Enterprise
    // would show "below in_use" the moment they submit.
    effect(() => {
      const floor = this.minSeats();
      if (this.selectedSeats() < floor) {
        this.selectedSeats.set(floor);
      }
    });
  }

  // ---- Template event handlers ------------------------------------------

  protected close(): void {
    if (this.isSubmitting()) return;
    this.modalState.close();
  }

  protected pickPlan(code: string): void {
    this.selectedPlan.set(code);
  }

  protected setCycle(cycle: BillingCycle): void {
    this.selectedCycle.set(cycle);
  }

  protected decrementSeats(): void {
    const next = this.selectedSeats() - 1;
    if (next < this.minSeats()) return;
    this.selectedSeats.set(next);
  }

  protected incrementSeats(): void {
    this.selectedSeats.set(this.selectedSeats() + 1);
  }

  protected isPopular(code: string): boolean {
    return code === POPULAR_PLAN_CODE;
  }

  protected planPriceFor(plan: PlanCatalogEntry): number {
    if (this.selectedCycle() === 'annual') {
      return Math.floor(plan.pricing.annual_bundle_usd / 12);
    }
    return plan.pricing.monthly_bundle_usd;
  }

  protected continueToPayment(): void {
    const plan = this.selectedPlan();
    if (plan === null || this.isSubmitting()) return;
    this.isSubmitting.set(true);
    this.submitError.set(null);

    const origin = window.location.origin;
    this.api
      .createCheckoutSession({
        to_plan: plan,
        billing_cycle: this.selectedCycle(),
        seats: this.selectedSeats(),
        success_url:
          origin +
          '/user/settings/billing/upgrade-success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url:
          origin + '/user/settings/billing/upgrade-cancel',
      })
      .subscribe({
        next: (response) => {
          // Hard redirect — Stripe Checkout is a separate hosted
          // experience; the SPA tears down deliberately.
          window.location.href = response.checkout_url;
        },
        error: (err) => {
          this.isSubmitting.set(false);
          this.submitError.set(extractErrorMessage(err));
        },
      });
  }

  // ---- Helpers -----------------------------------------------------------

  private fetchPlans(): void {
    this.plansLoading.set(true);
    this.plansError.set(false);
    this.api.getPlans().subscribe({
      next: (resp) => {
        this.plans.set(resp.plans);
        this.plansLoading.set(false);
      },
      error: () => {
        this.plansError.set(true);
        this.plansLoading.set(false);
      },
    });
  }
}


/** Pulls the structured backend error code into a user-readable
 *  inline message. Falls back to generic copy on unknown shapes so
 *  the modal never crashes on a surprise response. */
function extractErrorMessage(err: unknown): string {
  const e = err as {
    error?: { error?: string; in_use?: number; min_allowed?: number };
  };
  const code = e.error?.error;
  switch (code) {
    case 'seats_below_in_use':
      return `You have ${e.error?.in_use ?? 'too many'} active users — at least ${e.error?.min_allowed ?? 'enough'} seats are required.`;
    case 'seats_below_minimum':
      return `This plan requires at least ${e.error?.min_allowed ?? 5} seats.`;
    case 'cannot_change_to_trial':
      return 'Cannot downgrade to the trial plan.';
    case 'cannot_change_cancelled':
      return 'Your subscription is cancelled — contact support to reactivate.';
    case 'unknown_plan':
      return 'That plan is no longer available.';
    case 'invalid_redirect':
      return 'Payment provider rejected the redirect URL — please refresh and try again.';
    case 'payment_provider_unavailable':
      return 'Payments are temporarily unavailable. Please try again shortly.';
    default:
      return 'Something went wrong. Please try again.';
  }
}
