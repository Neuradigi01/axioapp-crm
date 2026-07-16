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
import {
  AdAttributionReport,
  ReportRange,
  WhatsAppReportsService,
} from './whatsapp-reports.service';

/**
 * Click-to-WhatsApp Ad ROI widget (whatsapp-platform-upgrade Step 24).
 *
 * Per-campaign table: conversations / leads / revenue. Sourced from
 * the `acquisition_*` columns on `tbl_conversations` (single-touch
 * attribution captured at first inbound). Empty state when no ad
 * traffic; "Unattributed" line aggregates ad-sourced conversations
 * where the Meta lookup didn't return a friendly campaign name.
 */
@Component({
  selector: 'app-wa-ad-roi-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Click-to-WhatsApp ROI
          </p>
          <p class="text-[11px] text-zinc-500">
            Conversations attributed to Meta Ads, with downstream lead + revenue.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-zinc-500">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        @if (r.rows.length === 0) {
          <p class="py-8 text-center text-xs text-zinc-500">
            No click-to-WhatsApp ad traffic in this window.
          </p>
        } @else {
          <div class="mb-3 grid grid-cols-3 gap-2">
            <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
              <p class="text-[10px] uppercase text-zinc-500">Conversations</p>
              <p class="text-lg font-semibold text-zinc-900">
                {{ r.total_conversations }}
              </p>
            </div>
            <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
              <p class="text-[10px] uppercase text-zinc-500">Leads</p>
              <p class="text-lg font-semibold text-emerald-700">
                {{ r.total_leads }}
              </p>
            </div>
            <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
              <p class="text-[10px] uppercase text-zinc-500">Revenue</p>
              <p class="text-lg font-semibold text-violet-700">
                {{ formatCurrency(r.total_revenue) }}
              </p>
            </div>
          </div>

          <table class="w-full text-xs">
            <thead class="text-zinc-500">
              <tr class="border-b border-zinc-200">
                <th class="py-1 text-left font-medium">Campaign</th>
                <th class="py-1 text-right font-medium">Conversations</th>
                <th class="py-1 text-right font-medium">Leads</th>
                <th class="py-1 text-right font-medium">Revenue</th>
              </tr>
            </thead>
            <tbody>
              @for (row of r.rows; track row.ad_id || row.campaign_id) {
                <tr class="border-b border-zinc-100 last:border-0">
                  <td class="py-1.5 text-zinc-800">
                    {{ row.campaign_name }}
                    @if (row.ad_name) {
                      <span class="text-zinc-500"> · {{ row.ad_name }}</span>
                    }
                  </td>
                  <td class="py-1.5 text-right text-zinc-700">{{ row.conversations }}</td>
                  <td class="py-1.5 text-right text-zinc-700">{{ row.leads }}</td>
                  <td class="py-1.5 text-right text-zinc-700">
                    {{ formatCurrency(row.revenue) }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      }
    </div>
  `,
})
export class AdRoiWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<AdAttributionReport | null>(null);

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  protected formatCurrency(value: number): string {
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 0,
      }).format(value);
    } catch {
      return `₹${value.toFixed(0)}`;
    }
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getAdAttribution(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load ad ROI.');
        },
      });
  }
}
