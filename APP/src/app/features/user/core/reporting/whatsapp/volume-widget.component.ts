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
  ApexStroke,
  ApexTooltip,
  ApexXAxis,
  ApexYAxis,
  NgApexchartsModule,
} from 'ng-apexcharts';

import { extractApiError } from '@core/services/api-error.util';
import {
  ReportGranularity,
  ReportRange,
  VolumeReport,
  WhatsAppReportsService,
} from './whatsapp-reports.service';

/**
 * WhatsApp message-volume widget (Step 20).
 *
 * Stacked area chart with 4 series (received, sent-human, sent-AI,
 * failed). Re-fetches whenever the parent's `range` or `granularity`
 * input flips.
 */
@Component({
  selector: 'app-wa-volume-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, NgApexchartsModule],
  template: `
    <div class="rounded-md border border-subtle bg-surface p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Message volume</p>
          <p class="text-[11px] text-muted">
            Customer + staff + AI traffic in the selected window.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-muted">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        <div class="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
          <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
            <p class="text-[10px] uppercase text-muted">Received</p>
            <p class="text-lg font-semibold text-default">{{ r.total_received }}</p>
          </div>
          <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
            <p class="text-[10px] uppercase text-muted">Sent (human)</p>
            <p class="text-lg font-semibold text-default">{{ r.total_sent }}</p>
          </div>
          <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
            <p class="text-[10px] uppercase text-muted">Sent (AI)</p>
            <p class="text-lg font-semibold text-violet-700 dark:text-violet-400">
              {{ r.total_ai_sent }}
            </p>
          </div>
          <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
            <p class="text-[10px] uppercase text-muted">Failed</p>
            <p class="text-lg font-semibold text-red-400">{{ r.total_failed }}</p>
          </div>
        </div>

        @if (r.buckets.length === 0) {
          <p class="py-8 text-center text-xs text-muted">No messages in this window.</p>
        } @else {
          <apx-chart
            [series]="series()"
            [chart]="chart"
            [xaxis]="xaxis()"
            [yaxis]="yaxis"
            [stroke]="stroke"
            [grid]="grid"
            [dataLabels]="dataLabels"
            [tooltip]="tooltip"
            [colors]="colors"
            [legend]="{ position: 'top', fontSize: '12px' }"
          />
        }
      }
    </div>
  `,
})
export class VolumeWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();
  readonly granularity = input.required<ReportGranularity>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<VolumeReport | null>(null);

  protected readonly chart: ApexChart = {
    type: 'area',
    height: 280,
    stacked: true,
    toolbar: { show: false },
    zoom: { enabled: false },
    animations: { enabled: false },
    fontFamily: 'inherit',
  };
  protected readonly stroke: ApexStroke = { curve: 'smooth', width: 2 };
  protected readonly grid: ApexGrid = {
    borderColor: '#e4e4e7',
    strokeDashArray: 3,
  };
  protected readonly dataLabels: ApexDataLabels = { enabled: false };
  protected readonly tooltip: ApexTooltip = { x: { format: 'dd MMM' } };
  protected readonly yaxis: ApexYAxis = {
    labels: { style: { fontSize: '11px' } },
  };
  protected readonly colors = ['#0ea5e9', '#22c55e', '#8b5cf6', '#f43f5e'];

  protected readonly series = signal<ApexAxisChartSeries>([]);

  protected readonly xaxis = (): ApexXAxis => ({
    type: 'datetime',
    labels: { style: { fontSize: '11px' } },
    axisBorder: { color: '#e4e4e7' },
    axisTicks: { color: '#e4e4e7' },
  });

  constructor() {
    effect(() => {
      const r = this.range();
      const g = this.granularity();
      this.fetch(r, g);
    });
  }

  private fetch(range: ReportRange, granularity: ReportGranularity): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getVolume(range, granularity)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.series.set([
            {
              name: 'Received',
              data: r.buckets.map((b) => [Date.parse(b.bucket_start), b.received]),
            },
            {
              name: 'Sent (human)',
              data: r.buckets.map((b) => [Date.parse(b.bucket_start), b.sent]),
            },
            {
              name: 'Sent (AI)',
              data: r.buckets.map((b) => [Date.parse(b.bucket_start), b.ai_sent]),
            },
            {
              name: 'Failed',
              data: r.buckets.map((b) => [Date.parse(b.bucket_start), b.failed]),
            },
          ]);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load message volume.');
        },
      });
  }
}
