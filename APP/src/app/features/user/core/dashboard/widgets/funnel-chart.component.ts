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
import { RouterLink } from '@angular/router';
import {
  ApexAxisChartSeries,
  ApexChart,
  ApexDataLabels,
  ApexGrid,
  ApexLegend,
  ApexPlotOptions,
  ApexTooltip,
  ApexXAxis,
  NgApexchartsModule,
} from 'ng-apexcharts';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';
import {
  dashboardRange,
  type DashboardRange,
} from '../shared/dashboard-range.signal';

interface FunnelStageBucket {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  count: number;
}

interface DashboardFunnelResponse {
  range: DashboardRange;
  scope: 'org' | 'personal';
  total_leads_in_range: number;
  stages: FunnelStageBucket[];
  won_count: number;
  lost_count: number;
}

// Zinc ramp from dark → light. Cycles for stages beyond index 5 so the
// chart stays readable even on pipelines with many stages.
const FUNNEL_COLORS = [
  '#18181b',
  '#27272a',
  '#3f3f46',
  '#52525b',
  '#71717a',
  '#a1a1aa',
];

/**
 * Dashboard funnel widget: ApexCharts horizontal-bar chart styled as a
 * pipeline funnel, plus won/lost counters in tiles below.
 *
 * ApexCharts' true funnel type is paywalled (apexcharts-pro); the
 * `bar.horizontal + distributed + zinc ramp` combination yields the
 * same visual on the free tier and keeps colour-per-stage stable
 * because the stage list is deterministic from the backend.
 *
 * Re-fetches automatically when `dashboardRange` changes.
 */
@Component({
  selector: 'app-dashboard-funnel-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, NgApexchartsModule],
  templateUrl: './funnel-chart.component.html',
})
export class FunnelChartComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal<boolean>(true);
  protected readonly error = signal<string | null>(null);
  protected readonly data = signal<DashboardFunnelResponse | null>(null);

  protected readonly series = computed<ApexAxisChartSeries>(() => {
    const d = this.data();
    if (!d) return [];
    return [
      {
        name: 'Leads',
        data: d.stages.map((s) => ({ x: s.stage_name, y: s.count })),
      },
    ];
  });

  protected readonly chart = computed<ApexChart>(() => ({
    type: 'bar',
    height: 256,
    toolbar: { show: false },
    animations: { enabled: true, speed: 250 },
    fontFamily: 'inherit',
  }));

  protected readonly plotOptions = computed<ApexPlotOptions>(() => ({
    bar: {
      horizontal: true,
      barHeight: '70%',
      borderRadius: 4,
      distributed: true,
      dataLabels: { position: 'center' },
    },
  }));

  protected readonly colors = computed<string[]>(() => FUNNEL_COLORS);

  protected readonly dataLabels = computed<ApexDataLabels>(() => ({
    enabled: true,
    style: { colors: ['#fff'], fontSize: '11px', fontWeight: 600 },
    formatter: (val: string | number | number[]) => {
      const n = typeof val === 'number' ? val : Number(val);
      if (!Number.isFinite(n) || n === 0) return '';
      return n.toString();
    },
  }));

  protected readonly xaxis = computed<ApexXAxis>(() => {
    const d = this.data();
    return {
      categories: d ? d.stages.map((s) => s.stage_name) : [],
      labels: {
        style: { colors: '#71717a', fontSize: '11px' },
      },
      axisBorder: { show: false },
      axisTicks: { show: false },
    };
  });

  protected readonly legend = computed<ApexLegend>(() => ({ show: false }));

  protected readonly tooltip = computed<ApexTooltip>(() => {
    const total = this.data()?.total_leads_in_range ?? 0;
    return {
      theme: 'light',
      y: {
        formatter: (val: number) => {
          const pct = total > 0 ? (val / total) * 100 : 0;
          return `${val} (${pct.toFixed(1)}% of total)`;
        },
      },
    };
  });

  protected readonly grid = computed<ApexGrid>(() => ({
    borderColor: '#f4f4f5',
    strokeDashArray: 4,
    padding: { left: 8, right: 8 },
  }));

  constructor() {
    effect(() => {
      const r = dashboardRange();
      this.load(r);
    });
  }

  private load(range: DashboardRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.http
      .get<DashboardFunnelResponse>(`${environment.apiBaseUrl}/dashboard/funnel`, {
        params: { range },
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.data.set(res);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? "Couldn't load funnel.");
          this.loading.set(false);
        },
      });
  }
}
