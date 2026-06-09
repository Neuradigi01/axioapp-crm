import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';

import { SubscriptionStateService } from '../../billing/services/subscription-state.service';
import { CurrentPlanCardComponent } from './components/current-plan-card.component';
import { SeatsCardComponent } from './components/seats-card.component';

/**
 * Billing settings tab.
 *
 * Sub-step 16.a (this commit) ships the Current plan + Seats cards.
 * Sub-step 16.b adds the Usage bars and Invoices table; Step 17
 * wires the Upgrade modal that the disabled CTAs here open.
 *
 * Data comes from the shared `SubscriptionStateService` (Step 15) —
 * the same instance that drives the trial banner. No new HTTP call
 * is made by this page in 16.a; the service already polled on app
 * load.
 *
 * Permission gating: the tab's parent (`settings-page.component`)
 * filters by `settings.write` for now. Step 19 introduces the
 * dedicated `billing.read` / `billing.manage` keys and swaps the
 * filter.
 */
@Component({
  selector: 'crm-billing-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CurrentPlanCardComponent, SeatsCardComponent],
  templateUrl: './billing.page.html',
  styleUrl: './billing.page.css',
})
export class BillingPage {
  private readonly state = inject(SubscriptionStateService);

  protected readonly subscription = this.state.current;
  protected readonly isLoading = computed(
    () => this.state.isLoading() && this.subscription() === null,
  );
  protected readonly loadError = computed(
    () => this.state.loadError() && this.subscription() === null,
  );

  protected retry(): void {
    this.state.refresh();
  }
}
