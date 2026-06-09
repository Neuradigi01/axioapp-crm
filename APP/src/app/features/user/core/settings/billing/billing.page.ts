import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';

import { SeatModalComponent } from '../../billing/components/seat-modal/seat-modal.component';
import { BillingApiService } from '../../billing/services/billing-api.service';
import { SubscriptionStateService } from '../../billing/services/subscription-state.service';
import { Invoice } from '../../billing/types/subscription.types';
import { CurrentPlanCardComponent } from './components/current-plan-card.component';
import { InvoicesTableComponent } from './components/invoices-table.component';
import { SeatsCardComponent } from './components/seats-card.component';
import { UsageBarsComponent } from './components/usage-bars.component';

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
  imports: [
    CurrentPlanCardComponent,
    SeatsCardComponent,
    UsageBarsComponent,
    InvoicesTableComponent,
    SeatModalComponent,
  ],
  templateUrl: './billing.page.html',
  styleUrl: './billing.page.css',
})
export class BillingPage implements OnInit {
  private readonly state = inject(SubscriptionStateService);
  private readonly api = inject(BillingApiService);

  protected readonly subscription = this.state.current;
  protected readonly isLoading = computed(
    () => this.state.isLoading() && this.subscription() === null,
  );
  protected readonly loadError = computed(
    () => this.state.loadError() && this.subscription() === null,
  );

  protected readonly invoices = signal<Invoice[]>([]);
  protected readonly invoicesLoading = signal<boolean>(true);

  ngOnInit(): void {
    this.loadInvoices();
  }

  protected retry(): void {
    this.state.refresh();
    this.loadInvoices();
  }

  private loadInvoices(): void {
    this.invoicesLoading.set(true);
    this.api.listInvoices().subscribe({
      next: (rows) => {
        this.invoices.set(rows);
        this.invoicesLoading.set(false);
      },
      error: () => {
        // Empty list + "no invoices yet" copy is the right UX when the
        // call fails — better than an error toast on a settings page.
        this.invoices.set([]);
        this.invoicesLoading.set(false);
      },
    });
  }
}
