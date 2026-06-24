import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
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
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

interface AbVariantBreakdown {
  variant: string;
  template_id: string | null;
  template_name: string | null;
  sent: number;
  delivered: number;
  read: number;
  replied: number;
  failed: number;
  reply_rate: number;
  read_rate: number;
}

interface AbComparisonReport {
  campaign_id: string;
  is_ab_test: boolean;
  winner_metric: 'reply_rate' | 'read_rate' | 'click_rate' | null;
  winning_variant: 'A' | 'B' | null;
  winner_decided_at: string | null;
  a: AbVariantBreakdown | null;
  b: AbVariantBreakdown | null;
}

/**
 * Step 29 — A/B variant side-by-side comparison on the
 * campaign-detail Analytics tab.
 *
 * Renders nothing for single-template campaigns (the API returns
 * `is_ab_test=false` and we hide the block entirely). For A/B
 * campaigns: a two-column table with per-variant counts + rates +
 * a winner banner that lights up once the decider has run.
 */
@Component({
  selector: 'app-ab-variant-comparison',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (loading()) {
      <p class="text-[11px] text-zinc-500">Loading A/B comparison…</p>
    }
    @if (error(); as err) {
      <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
        {{ err }}
      </p>
    }
    @if (report(); as r) {
      @if (r.is_ab_test && r.a && r.b) {
        <div class="rounded-md border border-zinc-200 bg-white p-4">
          <div class="mb-3 flex items-center justify-between">
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                A/B comparison
              </p>
              <p class="text-[11px] text-zinc-500">
                Winner metric: {{ humanMetric(r.winner_metric) }}
              </p>
            </div>
            @if (r.winning_variant) {
              <span
                class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200"
              >
                <lucide-icon name="check-check" class="h-3 w-3" />
                Winner: Variant {{ r.winning_variant }}
              </span>
            } @else {
              <span
                class="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
              >
                <lucide-icon name="clock" class="h-3 w-3" />
                Hold-back in progress
              </span>
            }
          </div>

          <table class="w-full text-xs">
            <thead class="text-zinc-500">
              <tr class="border-b border-zinc-200">
                <th class="py-1 text-left font-medium">Metric</th>
                <th class="py-1 text-right font-medium">Variant A</th>
                <th class="py-1 text-right font-medium">Variant B</th>
              </tr>
            </thead>
            <tbody>
              <tr class="border-b border-zinc-100">
                <td class="py-1.5 text-zinc-700">Template</td>
                <td class="py-1.5 text-right text-zinc-700">
                  {{ r.a.template_name || '—' }}
                </td>
                <td class="py-1.5 text-right text-zinc-700">
                  {{ r.b.template_name || '—' }}
                </td>
              </tr>
              <tr class="border-b border-zinc-100">
                <td class="py-1.5 text-zinc-700">Sent</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.a.sent }}</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.b.sent }}</td>
              </tr>
              <tr class="border-b border-zinc-100">
                <td class="py-1.5 text-zinc-700">Delivered</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.a.delivered }}</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.b.delivered }}</td>
              </tr>
              <tr class="border-b border-zinc-100">
                <td class="py-1.5 text-zinc-700">Read</td>
                <td
                  class="py-1.5 text-right text-zinc-700"
                  [class.font-semibold]="r.winner_metric === 'read_rate'"
                >
                  {{ r.a.read }} ({{ percent(r.a.read_rate) }}%)
                </td>
                <td
                  class="py-1.5 text-right text-zinc-700"
                  [class.font-semibold]="r.winner_metric === 'read_rate'"
                >
                  {{ r.b.read }} ({{ percent(r.b.read_rate) }}%)
                </td>
              </tr>
              <tr class="border-b border-zinc-100">
                <td class="py-1.5 text-zinc-700">Replied</td>
                <td
                  class="py-1.5 text-right text-zinc-700"
                  [class.font-semibold]="r.winner_metric === 'reply_rate'"
                >
                  {{ r.a.replied }} ({{ percent(r.a.reply_rate) }}%)
                </td>
                <td
                  class="py-1.5 text-right text-zinc-700"
                  [class.font-semibold]="r.winner_metric === 'reply_rate'"
                >
                  {{ r.b.replied }} ({{ percent(r.b.reply_rate) }}%)
                </td>
              </tr>
              <tr>
                <td class="py-1.5 text-zinc-700">Failed</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.a.failed }}</td>
                <td class="py-1.5 text-right text-zinc-700">{{ r.b.failed }}</td>
              </tr>
            </tbody>
          </table>

          @if (r.winning_variant && r.winner_decided_at) {
            <p class="mt-3 text-[11px] text-zinc-500">
              Winner decided at {{ formatDate(r.winner_decided_at) }}.
              Remaining unsent recipients (if any) receive the
              winning template automatically.
            </p>
          }
        </div>
      }
    }
  `,
})
export class AbVariantComparisonComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly campaignId = input.required<string>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<AbComparisonReport | null>(null);

  constructor() {
    effect(() => {
      const id = this.campaignId();
      if (id) this.fetch(id);
    });
  }

  protected percent(ratio: number): number {
    return Math.round((ratio ?? 0) * 100);
  }

  protected humanMetric(
    m: 'reply_rate' | 'read_rate' | 'click_rate' | null,
  ): string {
    switch (m) {
      case 'reply_rate':
        return 'Reply rate';
      case 'read_rate':
        return 'Read rate';
      case 'click_rate':
        return 'Click rate';
      default:
        return '—';
    }
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  private fetch(id: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.http
      .get<AbComparisonReport>(
        `${environment.apiBaseUrl}/reports/campaigns/${id}/ab-comparison`,
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not load A/B comparison.',
          );
        },
      });
  }
}
