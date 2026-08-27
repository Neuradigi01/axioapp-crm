import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';

import { InventoryApiService, InventoryItem, StockAlert } from '../inventory-api.service';

/**
 * Stock Alerts tab.
 *
 * Lists open alerts (high priority + most depleted first), shows the
 * matching item context, and exposes two actions per row:
 *
 *   - "Reorder"    → opens a modal to confirm qty + supplier.
 *                    On confirm: PATCH alert.status='ordered'.
 *                    Supplier/qty entered in the modal are UX-only
 *                    inputs today (no `receipt_planned` ledger row —
 *                    the alert status alone communicates "order in
 *                    flight"). When the real receipt is recorded, the
 *                    standard movement path auto-closes the alert.
 *   - "Mark Closed" → PATCH alert.status='closed' for the operator
 *                     who already restocked outside the system.
 */
interface AlertRow {
  alert: StockAlert;
  item: InventoryItem | null;
}

@Component({
  selector: 'app-fp-inventory-alerts',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './stock-alerts.component.html',
})
export class StockAlertsTabComponent {
  private readonly api = inject(InventoryApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder);

  protected readonly rows = signal<AlertRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  /** null = closed · AlertRow = reorder modal target. */
  protected readonly modalTarget = signal<AlertRow | null>(null);
  protected readonly busyAlertId = signal<string | null>(null);

  protected readonly reorderForm = this.fb.group({
    qty: this.fb.control(0, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(1)],
    }),
    supplier: this.fb.control<string>('', { nonNullable: true }),
    notes: this.fb.control<string>('', { nonNullable: true }),
  });

  /** Server already orders by (priority desc, created_at desc). For
   * ties on priority we sort by qty_on_hand ascending so the most
   * depleted item floats up. */
  protected readonly sortedRows = computed(() => {
    const pri = { high: 0, med: 1, low: 2 };
    return [...this.rows()].sort((a, b) => {
      const ap = pri[a.alert.priority];
      const bp = pri[b.alert.priority];
      if (ap !== bp) return ap - bp;
      const aq = a.item?.qty_on_hand ?? Infinity;
      const bq = b.item?.qty_on_hand ?? Infinity;
      return aq - bq;
    });
  });

  constructor() {
    this.reload();
  }

  protected severityBadge(s: StockAlert['severity']): {
    label: string;
    cls: string;
  } {
    return s === 'out'
      ? {
          label: 'Out of Stock',
          cls: 'bg-red-500/10 text-red-400 ring-red-500/20',
        }
      : {
          label: 'Low Stock',
          cls: 'bg-amber-50 text-amber-700 ring-amber-200',
        };
  }

  protected priorityBadge(p: StockAlert['priority']): {
    label: string;
    cls: string;
  } {
    switch (p) {
      case 'high':
        return {
          label: 'High',
          cls: 'bg-red-500/10 text-red-400 ring-red-500/30',
        };
      case 'med':
        return {
          label: 'Medium',
          cls: 'bg-amber-100 text-amber-800 ring-amber-300',
        };
      case 'low':
        return {
          label: 'Low',
          cls: 'bg-surface-2 text-default border-subtle',
        };
    }
  }

  protected openReorder(row: AlertRow): void {
    this.reorderForm.reset({
      qty: row.alert.suggested_reorder_qty || 1,
      supplier: '',
      notes: '',
    });
    this.modalTarget.set(row);
  }

  protected closeModal(): void {
    this.modalTarget.set(null);
  }

  protected confirmReorder(): void {
    const row = this.modalTarget();
    if (!row) return;
    if (!this.reorderForm.valid) {
      this.reorderForm.markAllAsTouched();
      return;
    }
    this.busyAlertId.set(row.alert.id);
    this.api
      .updateAlertStatus(row.alert.id, 'ordered')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busyAlertId.set(null);
          this.modalTarget.set(null);
          // Drop the now-ordered alert from the open list.
          this.rows.update((rows) => rows.filter((r) => r.alert.id !== updated.id));
        },
        error: (err: HttpErrorResponse) => {
          this.busyAlertId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not mark alert as ordered.');
        },
      });
  }

  protected markClosed(row: AlertRow): void {
    const ok = window.confirm(
      `Close alert for ${row.item?.sku ?? 'this item'}? Use this only if you've already restocked outside the system.`,
    );
    if (!ok) return;
    this.busyAlertId.set(row.alert.id);
    this.api
      .updateAlertStatus(row.alert.id, 'closed')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyAlertId.set(null);
          this.rows.update((rows) => rows.filter((r) => r.alert.id !== row.alert.id));
        },
        error: (err: HttpErrorResponse) => {
          this.busyAlertId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not close alert.');
        },
      });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listAlerts({ status: 'open' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (alerts) => {
          if (alerts.length === 0) {
            this.rows.set([]);
            this.loading.set(false);
            return;
          }
          // Batch-hydrate item context in ONE call via
          // `POST /inventory/items/hydrate` — was fanning out one
          // `GET /items/{id}` per alert.
          const ids = [...new Set(alerts.map((a) => a.item_id))];
          this.api
            .hydrateByIds(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (items) => {
                const byId = new Map<string, InventoryItem>();
                for (const it of items) {
                  byId.set(it.id, it);
                }
                const rows: AlertRow[] = alerts.map((alert) => ({
                  alert,
                  item: byId.get(alert.item_id) ?? null,
                }));
                this.rows.set(rows);
                this.loading.set(false);
              },
              error: () => {
                // Fallback: render alerts without item context.
                this.rows.set(alerts.map((a) => ({ alert: a, item: null })));
                this.loading.set(false);
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.rows.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load alerts.');
        },
      });
  }
}
