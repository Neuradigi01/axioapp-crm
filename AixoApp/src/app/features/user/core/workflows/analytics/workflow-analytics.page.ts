import { CommonModule, DatePipe, DecimalPipe, PercentPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  WorkflowAnalyticsResponse,
  WorkflowDailyRateRow,
  WorkflowFunnelRow,
  WorkflowRead,
  WorkflowsApiService,
} from '../workflows-api.service';

/**
 * Step 19 — per-workflow analytics dashboard.
 *
 * URL: `/user/workflows/:id/analytics`. Headline KPIs + funnel +
 * skip-reason drawer + daily-rate sparklines + per-channel send
 * rollup over a configurable (since, until) window (default 30d).
 *
 * Permission gate: `workflows.view_analytics` server-side. The
 * sidebar entry remains visible to Employees by default (per the
 * permission spec) — they see this page; only mutations are
 * gated tighter.
 */

const RANGE_PRESETS: Array<{ label: string; days: number }> = [
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
];

@Component({
  selector: 'app-workflow-analytics-page',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    DecimalPipe,
    PercentPipe,
    FormsModule,
    RouterLink,
    LucideAngularModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workflow-analytics.page.html',
})
export class WorkflowAnalyticsPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly workflowId = signal<string>('');
  readonly workflow = signal<WorkflowRead | null>(null);
  readonly analytics = signal<WorkflowAnalyticsResponse | null>(null);
  readonly dailyRate = signal<WorkflowDailyRateRow[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly rangeDays = signal(30);
  readonly rangePresets = RANGE_PRESETS;

  readonly drawerNode = signal<WorkflowFunnelRow | null>(null);

  readonly costFormatted = computed(() => {
    const cents = this.analytics()?.totals.estimated_cost_cents ?? 0;
    return (cents / 100).toFixed(2);
  });

  readonly funnelMax = computed(() => {
    const rows = this.analytics()?.funnel ?? [];
    return rows.reduce((acc, r) => Math.max(acc, r.total), 1);
  });

  readonly dailySparkPath = computed(() => this.buildSpark('enrolled'));
  readonly dailySparkCompletedPath = computed(() => this.buildSpark('completed'));
  readonly dailySparkGoalPath = computed(() => this.buildSpark('goal_reached'));

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((p) => {
      const id = p.get('id');
      if (id) this.workflowId.set(id);
    });

    effect(() => {
      const id = this.workflowId();
      const days = this.rangeDays();
      if (!id) return;
      this.refresh(id, days);
    });
  }

  refresh(workflowId: string, days: number): void {
    this.loading.set(true);
    this.error.set(null);
    const since = new Date();
    since.setUTCDate(since.getUTCDate() - days);
    forkJoin({
      workflow: this.api.get(workflowId),
      analytics: this.api.getAnalytics(workflowId, {
        since: since.toISOString(),
      }),
      daily: this.api.getDailyRate(workflowId, days),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ workflow, analytics, daily }) => {
          this.workflow.set(workflow);
          this.analytics.set(analytics);
          this.dailyRate.set(daily.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Analytics unavailable.');
          this.loading.set(false);
        },
      });
  }

  selectFunnelNode(node: WorkflowFunnelRow): void {
    this.drawerNode.set(node);
  }

  closeDrawer(): void {
    this.drawerNode.set(null);
  }

  skipReasonsFor(nodeId: string): Array<{ reason: string; count: number }> {
    const map = this.analytics()?.skip_reasons[nodeId] ?? {};
    return Object.entries(map)
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count);
  }

  funnelBarPct(row: WorkflowFunnelRow): number {
    const max = this.funnelMax();
    if (max <= 0) return 0;
    return Math.min(100, Math.round((row.total / max) * 100));
  }

  private buildSpark(field: 'enrolled' | 'completed' | 'goal_reached'): string {
    const rows = this.dailyRate();
    if (rows.length === 0) return '';
    const max = rows.reduce((acc, r) => Math.max(acc, r[field]), 1);
    const width = 240;
    const height = 36;
    const step = rows.length > 1 ? width / (rows.length - 1) : width;
    return rows
      .map((r, i) => {
        const x = i * step;
        const y = height - (r[field] / max) * height;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  }
}
