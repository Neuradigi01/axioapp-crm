import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Chart,
  ArcElement,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  DoughnutController,
  BarController,
  ChartConfiguration,
} from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { extractApiError } from '@core/services/api-error.util';

import { MobileDateTimeComponent } from '../../shared/forms/mobile-datetime.component';
import { CallAnalytics, CallsApiService } from '../calls-api.service';

// Register only the chart pieces we actually use. Tree-shaking-friendly.
Chart.register(
  ArcElement,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  DoughnutController,
  BarController,
);

/**
 * Analytics tab — three chart-ready arrays from `GET /calls/analytics`:
 *   - donut: outcomes distribution (colour = outcome's stored colour)
 *   - bar:   daily volume over the window
 *   - donut: direction split (incoming vs outgoing)
 *
 * `from` / `to` default to the last 14 days. Operator can change them
 * and the charts re-render via the same fetch path.
 */
@Component({
  selector: 'app-call-analytics-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, BaseChartDirective, MobileDateTimeComponent],
  templateUrl: './analytics.component.html',
})
export class CallAnalyticsTabComponent {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly data = signal<CallAnalytics | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly fromControl = new FormControl(this._isoDate(this._daysAgo(14)), {
    nonNullable: true,
  });
  protected readonly toControl = new FormControl(this._isoDate(new Date()), { nonNullable: true });

  // --- chart configs ----------------------------------------------------

  protected readonly outcomesChart = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const d = this.data();
    if (!d) return { labels: [], datasets: [] };
    return {
      labels: d.outcomes.map((r) => r.outcome_label ?? 'Not set'),
      datasets: [
        {
          data: d.outcomes.map((r) => r.count),
          backgroundColor: d.outcomes.map((r) => r.outcome_color ?? '#9ca3af'),
        },
      ],
    };
  });

  protected readonly dailyChart = computed<ChartConfiguration<'bar'>['data']>(() => {
    const d = this.data();
    if (!d) return { labels: [], datasets: [] };
    return {
      labels: d.daily.map((r) => r.day),
      datasets: [
        {
          data: d.daily.map((r) => r.count),
          label: 'Calls',
          backgroundColor: '#0ea5e9',
        },
      ],
    };
  });

  protected readonly directionChart = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const d = this.data();
    if (!d) return { labels: [], datasets: [] };
    return {
      labels: d.direction.map((r) => (r.direction === 'out' ? 'Outgoing' : 'Incoming')),
      datasets: [
        {
          data: d.direction.map((r) => r.count),
          backgroundColor: d.direction.map((r) => (r.direction === 'out' ? '#10b981' : '#0ea5e9')),
        },
      ],
    };
  });

  protected readonly doughnutOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom' } },
  };

  protected readonly barOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      y: { beginAtZero: true, ticks: { precision: 0 } },
    },
  };

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .analytics(this.fromControl.value, this.toControl.value)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (d) => {
          this.data.set(d);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.data.set(null);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load analytics.');
        },
      });
  }

  protected totalCalls(): number {
    const d = this.data();
    if (!d) return 0;
    return d.direction.reduce((acc, r) => acc + r.count, 0);
  }

  private _daysAgo(n: number): Date {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d;
  }

  private _isoDate(d: Date): string {
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
}
