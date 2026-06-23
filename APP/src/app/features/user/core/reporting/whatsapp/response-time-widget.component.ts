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
import {
  ApexAxisChartSeries,
  ApexChart,
  ApexDataLabels,
  ApexGrid,
  ApexPlotOptions,
  ApexXAxis,
  ApexYAxis,
  NgApexchartsModule,
} from 'ng-apexcharts';

import { extractApiError } from '@core/services/api-error.util';
import {
  ReportRange,
  ResponseTimeReport,
  WhatsAppReportsService,
  formatDuration,
} from './whatsapp-reports.service';

/**
 * First-staff-reply latency widget (Step 20).
 *
 * Three blocks:
 *   1. Big median + p95 KPIs over the whole window.
 *   2. Distribution bar chart (`< 1min` / `1–5 min` / ...).
 *   3. Per-agent breakdown table.
 *
 * AI replies don't count toward this metric — server filters them
 * out. Conversations with no human reply contribute zero samples.
 */
@Component({
  selector: 'app-wa-response-time-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, NgApexchartsModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            First staff response time
          </p>
          <p class="text-[11px] text-zinc-500">
            Time from a customer's first inbound to a human agent's first reply.
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
        <div class="mb-4 grid grid-cols-3 gap-2">
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">Median</p>
            <p class="text-lg font-semibold text-zinc-900">
              {{ formatDuration(r.overall_median_seconds) }}
            </p>
          </div>
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">p95</p>
            <p class="text-lg font-semibold text-zinc-900">
              {{ formatDuration(r.overall_p95_seconds) }}
            </p>
          </div>
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">Samples</p>
            <p class="text-lg font-semibold text-zinc-900">
              {{ r.sample_size }}
            </p>
          </div>
        </div>

        @if (r.sample_size === 0) {
          <p class="py-6 text-center text-xs text-zinc-500">
            No customer-to-agent replies in this window.
          </p>
        } @else {
          <apx-chart
            [series]="series()"
            [chart]="chart"
            [xaxis]="xaxis()"
            [yaxis]="yaxis"
            [plotOptions]="plotOptions"
            [grid]="grid"
            [dataLabels]="dataLabels"
            [colors]="colors"
            [legend]="{ show: false }"
          />

          @if (r.groups.length > 0) {
            <div class="mt-4">
              <p class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                Per-agent
              </p>
              <table class="w-full text-xs">
                <thead class="text-zinc-500">
                  <tr class="border-b border-zinc-200">
                    <th class="py-1 text-left font-medium">Agent</th>
                    <th class="py-1 text-right font-medium">Median</th>
                    <th class="py-1 text-right font-medium">p95</th>
                    <th class="py-1 text-right font-medium">Samples</th>
                  </tr>
                </thead>
                <tbody>
                  @for (g of r.groups; track g.key) {
                    <tr class="border-b border-zinc-100 last:border-0">
                      <td class="py-1 text-zinc-800">{{ g.label }}</td>
                      <td class="py-1 text-right text-zinc-700">
                        {{ formatDuration(g.median_seconds) }}
                      </td>
                      <td class="py-1 text-right text-zinc-700">
                        {{ formatDuration(g.p95_seconds) }}
                      </td>
                      <td class="py-1 text-right text-zinc-700">
                        {{ g.sample_size }}
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        }
      }
    </div>
  `,
})
export class ResponseTimeWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();

  protected readonly formatDuration = formatDuration;

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<ResponseTimeReport | null>(null);
  protected readonly series = signal<ApexAxisChartSeries>([]);
  protected readonly categories = signal<string[]>([]);

  protected readonly chart: ApexChart = {
    type: 'bar',
    height: 220,
    toolbar: { show: false },
    fontFamily: 'inherit',
    animations: { enabled: false },
  };
  protected readonly plotOptions: ApexPlotOptions = {
    bar: { borderRadius: 4, columnWidth: '55%' },
  };
  protected readonly grid: ApexGrid = {
    borderColor: '#e4e4e7',
    strokeDashArray: 3,
  };
  protected readonly dataLabels: ApexDataLabels = { enabled: false };
  protected readonly yaxis: ApexYAxis = {
    labels: { style: { fontSize: '11px' } },
  };
  protected readonly colors = ['#3b82f6'];

  protected readonly xaxis = (): ApexXAxis => ({
    categories: this.categories(),
    labels: { style: { fontSize: '11px' } },
    axisBorder: { color: '#e4e4e7' },
    axisTicks: { color: '#e4e4e7' },
  });

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getResponseTime(range, 'agent')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.categories.set(r.distribution.map((d) => d.label));
          this.series.set([
            {
              name: 'Conversations',
              data: r.distribution.map((d) => d.count),
            },
          ]);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not load response times.',
          );
        },
      });
  }
}
