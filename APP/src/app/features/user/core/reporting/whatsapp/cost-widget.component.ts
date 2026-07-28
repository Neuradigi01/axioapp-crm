import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import { CostReport, ReportRange, WhatsAppReportsService } from './whatsapp-reports.service';

/**
 * Estimated cost widget (Step 21).
 *
 * Total + per-category breakdown for the active range. Labelled
 * "Estimate" because we don't have the Meta invoice API — list-rate
 * × volume only.
 *
 * The region defaults to `IN` (FurnitureCRM's primary market); we
 * could persist it on the org later, but Step 21 keeps it as a
 * widget-local toggle until Phase 8's settings work.
 */
@Component({
  selector: 'app-wa-cost-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-subtle bg-surface p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Estimated cost</p>
          <p class="text-[11px] text-muted">List-rate estimate, not the Meta invoice.</p>
        </div>
        <div
          class="inline-flex items-center rounded-md border border-subtle bg-surface p-0.5 text-[11px]"
          role="tablist"
          aria-label="Region"
        >
          @for (r of REGIONS; track r) {
            <button
              type="button"
              [class]="
                'rounded px-2 py-0.5 ' +
                (region() === r ? 'bg-accent text-white' : 'text-default hover:bg-surface-2')
              "
              (click)="region.set(r)"
            >
              {{ r }}
            </button>
          }
        </div>
      </div>

      @if (loading()) {
        <p class="text-[11px] text-muted">Loading…</p>
      }
      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        <p class="mb-3 text-2xl font-semibold text-default">
          {{ formatCurrency(r.total, r.currency) }}
        </p>
        <table class="w-full text-xs">
          <thead class="text-muted">
            <tr class="border-b border-subtle">
              <th class="py-1 text-left font-medium">Category</th>
              <th class="py-1 text-right font-medium">Count</th>
              <th class="py-1 text-right font-medium">Rate</th>
              <th class="py-1 text-right font-medium">Subtotal</th>
            </tr>
          </thead>
          <tbody>
            @for (l of r.lines; track l.category) {
              <tr class="border-b border-subtle last:border-0">
                <td class="py-1 capitalize text-default">{{ l.category }}</td>
                <td class="py-1 text-right text-default">{{ l.count }}</td>
                <td class="py-1 text-right text-default">
                  {{ formatCurrency(l.rate, l.currency) }}
                </td>
                <td class="py-1 text-right text-default">
                  {{ formatCurrency(l.total, l.currency) }}
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </div>
  `,
})
export class CostWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();

  protected readonly REGIONS = ['IN', 'AE', 'US'] as const;
  protected readonly region = signal<(typeof this.REGIONS)[number]>('IN');

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<CostReport | null>(null);

  constructor() {
    effect(() => {
      const r = this.range();
      const reg = this.region();
      this.fetch(r, reg);
    });
  }

  protected formatCurrency(value: number, currency: string): string {
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency,
        maximumFractionDigits: 2,
      }).format(value);
    } catch {
      return `${currency} ${value.toFixed(2)}`;
    }
  }

  private fetch(range: ReportRange, region: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getCost(range, region)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load cost.');
        },
      });
  }
}
