import {
  ChangeDetectionStrategy,
  Component,
  signal,
} from '@angular/core';

import { ProductsTabComponent } from './tabs/products.component';

export type InventoryTabId = 'products' | 'alerts';

/**
 * Inventory & Warehouse page — top-level tab host. Today renders:
 *
 *   - Products  (this step — grid/list of inventory items)
 *   - Alerts    (Step 4.6 — placeholder card today)
 *
 * Movements UI is folded into a per-item drawer in Step 4.7, not a
 * separate tab.
 */
@Component({
  selector: 'app-fp-inventory-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ProductsTabComponent],
  templateUrl: './inventory.page.html',
})
export class InventoryPageComponent {
  protected readonly activeTab = signal<InventoryTabId>('products');

  protected readonly tabs: ReadonlyArray<{ id: InventoryTabId; label: string }> = [
    { id: 'products', label: 'Products' },
    { id: 'alerts', label: 'Stock Alerts' },
  ];

  protected setTab(t: InventoryTabId): void {
    this.activeTab.set(t);
  }
}
