import {
  ChangeDetectionStrategy,
  Component,
  signal,
} from '@angular/core';

import { InvoicesTabComponent } from './tabs/invoices.component';
import { PosTabComponent } from './tabs/pos.component';

export type BillingTabId = 'invoices' | 'pos';

/**
 * Billing & POS tab host — same shell shape as the Inventory page.
 * Two tabs: Invoices (history + status filter + summary tiles) and POS
 * (catalog grid + cart + checkout panel). Each tab is self-contained;
 * navigation is purely signal-driven, no router state needed.
 */
@Component({
  selector: 'app-fp-billing-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InvoicesTabComponent, PosTabComponent],
  templateUrl: './billing.page.html',
})
export class BillingPageComponent {
  protected readonly activeTab = signal<BillingTabId>('invoices');
  protected readonly tabs: ReadonlyArray<{
    id: BillingTabId;
    label: string;
  }> = [
    { id: 'invoices', label: 'Invoices' },
    { id: 'pos', label: 'POS' },
  ];

  protected setTab(t: BillingTabId): void {
    this.activeTab.set(t);
  }
}
