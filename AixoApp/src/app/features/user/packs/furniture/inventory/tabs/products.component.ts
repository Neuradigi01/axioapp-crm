import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { InventoryApiService, InventoryItem, Warehouse } from '../inventory-api.service';
import { AddProductModalComponent } from '../add-product-modal.component';
import { ProductCardComponent } from '../product-card.component';
import { extractApiError } from '@core/services/api-error.util';

type ViewMode = 'grid' | 'list';

/**
 * Products tab — main inventory grid.
 *
 *   - Filters: warehouse (dropdown), search (debounced), active-only
 *     toggle, view-mode grid/list.
 *   - Cards render via `ProductCardComponent`; list view is a table
 *     with the same data + the badge collapsed into a status column.
 *   - Pagination is server-side (page/size). Cursor pagination was
 *     stub'd in the step plan but the backend `/items` endpoint uses
 *     page/size today, so we mirror that here.
 *
 * Category filter is wired but inert until catalog items have
 * categories populated — the dropdown stays empty by default and the
 * field just passes through to `category=` query.
 */
@Component({
  selector: 'app-fp-inventory-products',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    ProductCardComponent,
    AddProductModalComponent,
  ],
  templateUrl: './products.component.html',
})
export class ProductsTabComponent {
  private readonly api = inject(InventoryApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<InventoryItem[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly warehouses = signal<Warehouse[]>([]);

  protected readonly viewMode = signal<ViewMode>('grid');
  protected readonly searchControl = new FormControl('', { nonNullable: true });
  protected readonly warehouseFilter = signal<string>('');
  protected readonly activeOnly = signal<boolean>(false);
  protected readonly modalOpen = signal(false);

  protected readonly warehouseById = computed(() => {
    const m = new Map<string, Warehouse>();
    for (const w of this.warehouses()) m.set(w.id, w);
    return m;
  });

  constructor() {
    this.loadWarehouses();
    this.reloadItems();

    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reloadItems());
  }

  protected setViewMode(mode: ViewMode): void {
    this.viewMode.set(mode);
  }

  protected openAddModal(): void {
    this.modalOpen.set(true);
  }

  protected onProductCreated(_item: InventoryItem): void {
    this.modalOpen.set(false);
    this.reloadItems();
  }

  protected onAddCancel(): void {
    this.modalOpen.set(false);
  }

  protected onWarehouseChange(event: Event): void {
    this.warehouseFilter.set((event.target as HTMLSelectElement).value);
    this.reloadItems();
  }

  protected toggleActiveOnly(): void {
    this.activeOnly.update((v) => !v);
    this.reloadItems();
  }

  protected warehouseLabelFor(item: InventoryItem): string | null {
    return this.warehouseById().get(item.warehouse_id)?.name ?? null;
  }

  protected statusFor(item: InventoryItem): { label: string; cls: string } {
    if (item.qty_on_hand <= 0) {
      return {
        label: 'Out of Stock',
        cls: 'bg-red-500/10 text-red-400 ring-red-500/20',
      };
    }
    if (item.reorder_level > 0 && item.qty_on_hand <= item.reorder_level) {
      return {
        label: 'Low Stock',
        cls: 'bg-amber-50 text-amber-700 ring-amber-200',
      };
    }
    return {
      label: 'In Stock',
      cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    };
  }

  private loadWarehouses(): void {
    this.api
      .listWarehouses()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.warehouses.set(rows),
        error: () => this.warehouses.set([]),
      });
  }

  private reloadItems(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listItems({
        warehouse_id: this.warehouseFilter() || undefined,
        q: this.searchControl.value.trim() || undefined,
        active_only: this.activeOnly() || undefined,
        size: 200,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load inventory items.');
        },
      });
  }
}
