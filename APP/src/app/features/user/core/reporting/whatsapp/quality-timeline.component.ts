import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ApexAnnotations,
  ApexAxisChartSeries,
  ApexChart,
  ApexDataLabels,
  ApexGrid,
  ApexStroke,
  ApexXAxis,
  ApexYAxis,
  NgApexchartsModule,
} from 'ng-apexcharts';

import { extractApiError } from '@core/services/api-error.util';
import {
  QualityTimelineReport,
  ReportRange,
  WhatsAppReportsService,
} from './whatsapp-reports.service';

/**
 * Quality timeline (Step 21).
 *
 * Daily send-volume line with vertical annotations at each Meta-side
 * phone-quality / tier / restriction change (sourced from
 * `tbl_whatsapp_phone_health_events` — Step 12). The operator sees
 * "we spiked sends on the 14th and got flagged YELLOW on the 16th"
 * without juggling tabs.
 */
@Component({
  selector: 'app-wa-quality-timeline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, NgApexchartsModule],
  template: `
    <div class="rounded-md border border-subtle bg-surface p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Quality timeline</p>
          <p class="text-[11px] text-muted">
            Daily send volume with phone-quality / tier changes annotated.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-muted">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        @if (r.volume.length === 0) {
          <p class="py-8 text-center text-xs text-muted">No outbound traffic in this window.</p>
        } @else {
          <apx-chart
            [series]="series()"
            [chart]="chart"
            [xaxis]="xaxis"
            [yaxis]="yaxis"
            [stroke]="stroke"
            [grid]="grid"
            [dataLabels]="dataLabels"
            [annotations]="annotations()"
            [colors]="colors"
            [legend]="{ show: false }"
          />

          @if (r.events.length > 0) {
            <ul class="mt-3 space-y-1 text-[11px] text-muted">
              @for (e of r.events; track e.occurred_at) {
                <li class="flex items-center gap-2">
                  <span
                    class="inline-flex h-2 w-2 rounded-full"
                    [class]="eventDot(e.event_type)"
                  ></span>
                  <span class="text-muted">{{ formatDate(e.occurred_at) }}</span>
                  <span class="font-medium text-default">
                    {{ humanEvent(e.event_type) }}
                  </span>
                  @if (e.new_value) {
                    <span class="text-muted">→ {{ e.new_value }}</span>
                  }
                </li>
              }
            </ul>
          }
        }
      }
    </div>
  `,
})
export class QualityTimelineComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<QualityTimelineReport | null>(null);

  protected readonly chart: ApexChart = {
    type: 'line',
    height: 280,
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
  protected readonly xaxis: ApexXAxis = {
    type: 'datetime',
    labels: { style: { fontSize: '11px' } },
    axisBorder: { color: '#e4e4e7' },
    axisTicks: { color: '#e4e4e7' },
  };
  protected readonly yaxis: ApexYAxis = {
    labels: { style: { fontSize: '11px' } },
  };
  protected readonly colors = ['#0ea5e9'];

  protected readonly series = computed<ApexAxisChartSeries>(() => {
    const r = this.report();
    if (!r) return [];
    return [
      {
        name: 'Daily sent',
        data: r.volume.map((b) => [Date.parse(b.bucket_start), b.sent]),
      },
    ];
  });

  protected readonly annotations = computed<ApexAnnotations>(() => {
    const r = this.report();
    if (!r) return {};
    return {
      xaxis: r.events.map((e) => ({
        x: Date.parse(e.occurred_at),
        strokeDashArray: 4,
        borderColor: this.eventStrokeHex(e.event_type),
        label: {
          borderColor: this.eventStrokeHex(e.event_type),
          style: {
            color: '#fff',
            background: this.eventStrokeHex(e.event_type),
            fontSize: '10px',
          },
          text: this.humanEvent(e.event_type),
        },
      })),
    };
  });

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  protected humanEvent(t: string): string {
    return (
      (
        {
          quality_change: 'Quality',
          tier_change: 'Tier',
          name_status_change: 'Display name',
          restriction_added: 'Restriction',
          restriction_lifted: 'Restriction lifted',
        } as Record<string, string>
      )[t] ?? t
    );
  }

  protected eventDot(t: string): string {
    switch (t) {
      case 'restriction_added':
        return 'bg-rose-500';
      case 'restriction_lifted':
        return 'bg-emerald-500';
      case 'quality_change':
        return 'bg-amber-500';
      case 'tier_change':
        return 'bg-blue-500';
      default:
        return 'bg-muted';
    }
  }

  protected eventStrokeHex(t: string): string {
    switch (t) {
      case 'restriction_added':
        return '#f43f5e';
      case 'restriction_lifted':
        return '#10b981';
      case 'quality_change':
        return '#f59e0b';
      case 'tier_change':
        return '#3b82f6';
      default:
        return '#52525b';
    }
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString();
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getQualityTimeline(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load quality timeline.');
        },
      });
  }
}
