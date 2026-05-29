import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ApexAxisChartSeries,
  ApexChart,
  ApexDataLabels,
  ApexFill,
  ApexGrid,
  ApexStroke,
  ApexTooltip,
  ApexXAxis,
  ApexYAxis,
  NgApexchartsModule,
} from 'ng-apexcharts';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';
import {
  dashboardRange,
  type DashboardRange,
} from '../shared/dashboard-range.signal';

type TrendMetric = 'leads_created' | 'pipeline_value' | 'calls' | 'appointments';

interface DashboardTrendResponse {
  metric: TrendMetric;
  range: DashboardRange;
  scope: 'org' | 'personal';
  points: { date: string; value: number }[];
}

/**
 * Dashboard trend widget: ApexCharts area-line backed by `/dashboard/trend`.
 *
 * Re-fetches automatically whenever the user switches metric or the
 * shared `dashboardRange` signal changes — the `effect()` reads both,
 * so Angular's signal graph drives the lifecycle. No manual subscribe
 * to the range or manual `update()` calls on the chart instance.
 *
 * Scope-blind by design — the API filters per-caller, and the chart
 * just plots whatever it's given.
 */
@Component({
  selector: 'app-dashboard-trend-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, NgApexchartsModule],
  templateUrl: './trend-chart.component.html',
})
export class TrendChartComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly METRICS: ReadonlyArray<{ key: TrendMetric; label: string }> = [
    { key: 'leads_created', label: 'Leads created' },
    { key: 'pipeline_value', label: 'Pipeline value' },
    { key: 'calls', label: 'Calls' },
    { key: 'appointments', label: 'Appointments' },
  ];

  protected readonly metric = signal<TrendMetric>('leads_created');
  protected readonly loading = signal<boolean>(true);
  protected readonly error = signal<string | null>(null);
  protected readonly series = signal<ApexAxisChartSeries>([
    { name: 'Leads created', data: [] },
  ]);

  protected readonly chart = computed<ApexChart>(() => ({
    type: 'area',
    height: 256,
    toolbar: { show: false },
    zoom: { enabled: false },
    animations: { enabled: true, speed: 250 },
    fontFamily: 'inherit',
  }));

  protected readonly stroke = computed<ApexStroke>(() => ({
    curve: 'smooth',
    width: 2,
  }));

  protected readonly fill = computed<ApexFill>(() => ({
    type: 'gradient',
    gradient: {
      shadeIntensity: 1,
      opacityFrom: 0.4,
      opacityTo: 0.05,
      stops: [0, 90, 100],
    },
  }));

  protected readonly colors = computed<string[]>(() => ['#18181b']);

  protected readonly dataLabels = computed<ApexDataLabels>(() => ({
    enabled: false,
  }));

  protected readonly xaxis = computed<ApexXAxis>(() => ({
    type: 'datetime',
    labels: {
      style: { colors: '#71717a', fontSize: '11px' },
      datetimeUTC: false,
    },
    axisBorder: { show: false },
    axisTicks: { show: false },
  }));

  protected readonly yaxis = computed<ApexYAxis>(() => {
    const m = this.metric();
    return {
      labels: {
        style: { colors: '#71717a', fontSize: '11px' },
        formatter: (v: number) => {
          if (m === 'pipeline_value') {
            try {
              return new Intl.NumberFormat('en-IN', {
                style: 'currency',
                currency: 'INR',
                maximumFractionDigits: 0,
              }).format(v);
            } catch {
              return `₹${Math.round(v).toLocaleString()}`;
            }
          }
          return Math.round(v).toString();
        },
      },
    };
  });

  protected readonly tooltip = computed<ApexTooltip>(() => ({
    theme: 'light',
    x: { format: 'dd MMM yyyy' },
  }));

  protected readonly grid = computed<ApexGrid>(() => ({
    borderColor: '#f4f4f5',
    strokeDashArray: 4,
    padding: { left: 8, right: 8 },
  }));

  constructor() {
    effect(() => {
      const m = this.metric();
      const r = dashboardRange();
      this.load(m, r);
    });
  }

  protected setMetric(next: TrendMetric): void {
    this.metric.set(next);
  }

  private load(metric: TrendMetric, range: DashboardRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.http
      .get<DashboardTrendResponse>(`${environment.apiBaseUrl}/dashboard/trend`, {
        params: { metric, range },
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          const label =
            this.METRICS.find((x) => x.key === metric)?.label ?? metric;
          this.series.set([
            {
              name: label,
              data: res.points.map((p) => ({
                x: new Date(p.date).getTime(),
                y: p.value,
              })),
            },
          ]);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? "Couldn't load trend.");
          this.loading.set(false);
        },
      });
  }
}
