import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { PlanCompareTableComponent } from '../components/plan-compare-table/plan-compare-table.component';
import { SeatModalComponent } from '../components/seat-modal/seat-modal.component';
import { BillingApiService } from '../services/billing-api.service';
import { SubscriptionStateService } from '../services/subscription-state.service';
import { Invoice, PlanCatalogEntry } from '../types/subscription.types';
import { CurrentPlanCardComponent } from './components/current-plan-card.component';
import { InvoicesTableComponent } from './components/invoices-table.component';
import { SeatsCardComponent } from './components/seats-card.component';
import { UsageBarsComponent } from './components/usage-bars.component';

/**
 * Billing page — Owner-only sidebar module, mounted at `/user/subscription`.
 *
 * Renders the Current plan + Seats + Usage bars + Invoices table.
 * Data comes from the shared `SubscriptionStateService` — the same
 * instance that drives the trial banner. Permission gating is at the
 * route level (`billing.manage`).
 */
@Component({
  selector: 'crm-billing-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    CurrentPlanCardComponent,
    SeatsCardComponent,
    UsageBarsComponent,
    InvoicesTableComponent,
    SeatModalComponent,
    PlanCompareTableComponent,
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

  /** Plan catalogue for the "What's in each plan" comparison card.
   *  Fetched once on init — the upgrade modal fetches this itself so
   *  the page doesn't need to pre-warm; keeping it local here so the
   *  card renders even for orgs that never open the upgrade flow. */
  protected readonly plans = signal<PlanCatalogEntry[]>([]);

  /** Match key for the comparison table's "Current plan" pill. Falls
   *  back to null when the subscription isn't loaded yet — the
   *  compare-table component treats null as "don't highlight". */
  protected readonly currentPlanCode = computed(() => this.subscription()?.plan?.code ?? null);

  ngOnInit(): void {
    this.loadInvoices();
    this.loadPlans();
  }

  protected retry(): void {
    this.state.refresh();
    this.loadInvoices();
    this.loadPlans();
  }

  private loadPlans(): void {
    this.api.getPlans().subscribe({
      next: (resp) => this.plans.set(resp.plans),
      error: () => {
        // Comparison table is a nice-to-have; if the fetch fails just
        // hide the card silently. The current-plan card + usage + seats
        // are the primary billing UX and drive from a different call.
        this.plans.set([]);
      },
    });
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
