import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { PlanCardComponent } from './plan-card.component';
import { PricingApiService } from './pricing-api.service';
import { BillingCycle, Plan } from './pricing.types';

/**
 * Public `/pricing` page.
 *
 * Reachable without auth (sits peer to `/accounts/...` and `/user/...`
 * in the top-level route tree). Renders the three public plans
 * (Basic / Standard / Enterprise) in a comparison grid with a
 * monthly/annual cycle toggle.
 *
 * Card feature lists are MARKETING copy hardcoded here, *not* the
 * full entitlement registry from `plans.yaml`. When the YAML adds a
 * flagship feature, the corresponding `CARD_FEATURES` entry must be
 * updated by hand. The entitlement service (Step 3) remains the
 * source of truth at runtime; this page is a summary for buyers.
 *
 * The "Start free trial" CTA carries the chosen `plan` + `cycle` as
 * query params so the signup flow (Step 17) can drop the user into
 * auto-checkout for the right plan after they create an org.
 */

/** Curated feature copy per plan code. Trial is omitted (it's not on
 *  the marketing page). */
const CARD_FEATURES: Record<string, readonly string[]> = {
  basic: [
    'Contacts, Leads, Walk-ins',
    'Pipelines (1)',
    'Tasks & Calendar',
    'Email templates (5)',
    'CSV import / export',
    'Basic dashboard',
    'Email support',
  ],
  standard: [
    'Everything in Basic, plus:',
    'Workflow automation',
    'Unified inbox (WhatsApp + Email + SMS)',
    'Google Ads + Meta Ads lead capture',
    'Call recording',
    'Email integration (IMAP / SMTP)',
    'Public REST API',
    'Email & SMS campaigns',
    'Advanced reports',
    'Chat support',
  ],
  enterprise: [
    'Everything in Standard, plus:',
    'SSO / SAML',
    'Audit logs',
    'Multi-branch',
    'White-label',
    'AI lead scoring',
    'Offline conversion sync to Ads',
    'Unlimited API',
    'Dedicated CSM + SLA',
  ],
};

/** Plan code shown with the "Most popular" ribbon. */
const POPULAR_PLAN_CODE = 'standard';

@Component({
  selector: 'crm-pricing-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PlanCardComponent, RouterLink],
  templateUrl: './pricing.page.html',
  styleUrl: './pricing.page.css',
})
export class PricingPage implements OnInit {
  private readonly api = inject(PricingApiService);

  protected readonly cycle = signal<BillingCycle>('monthly');
  protected readonly plans = signal<Plan[]>([]);
  protected readonly isLoading = signal<boolean>(true);
  protected readonly loadError = signal<boolean>(false);

  /** Plans sorted by `display_order` so Basic → Standard → Enterprise
   *  is stable even if the API returns them out of order. */
  protected readonly sortedPlans = computed(() =>
    [...this.plans()].sort((a, b) => a.display_order - b.display_order),
  );

  ngOnInit(): void {
    this.loadPlans();
  }

  protected loadPlans(): void {
    this.isLoading.set(true);
    this.loadError.set(false);
    this.api.getPlans().subscribe({
      next: (response) => {
        this.plans.set(response.plans);
        this.isLoading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  protected setCycle(next: BillingCycle): void {
    this.cycle.set(next);
  }

  /** Lookup helpers consumed by the template. */
  protected featuresFor(planCode: string): readonly string[] {
    return CARD_FEATURES[planCode] ?? [];
  }

  protected isPopular(planCode: string): boolean {
    return planCode === POPULAR_PLAN_CODE;
  }
}
