import { CommonModule, DatePipe, PercentPipe } from '@angular/common';
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
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  ABStatsResponse,
  WorkflowRead,
  WorkflowsApiService,
} from '../workflows-api.service';


/**
 * Step 18 — full-page side-by-side A/B comparison. Renders both
 * variants' headline stats, the live z-test verdict, holdback /
 * decision timeline, and a per-variant goal-rate sparkline (best-fit
 * straight-line for now; richer time series lands in a follow-up
 * when run telemetry exposes per-day aggregates).
 *
 * URL: `/user/workflows/:id/ab-compare`. Reached from the banner
 * above the canvas and from the workflows list page once the row is
 * paired.
 */


const REFRESH_INTERVAL_MS = 60_000;


@Component({
  selector: 'app-ab-comparison-page',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    PercentPipe,
    RouterLink,
    LucideAngularModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ab-comparison.page.html',
})
export class ABComparisonPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly workflowId = signal<string>('');

  readonly stats = signal<ABStatsResponse | null>(null);
  readonly aWorkflow = signal<WorkflowRead | null>(null);
  readonly bWorkflow = signal<WorkflowRead | null>(null);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly winnerCalled = computed(() => this.stats()?.decided_at != null);

  readonly winner = computed(() => this.stats()?.winner ?? 'inconclusive');

  readonly aIsWinner = computed(() => this.winnerCalled() && this.winner() === 'a');
  readonly bIsWinner = computed(() => this.winnerCalled() && this.winner() === 'b');

  readonly pValueLabel = computed(() => {
    const p = this.stats()?.p_value;
    if (p === null || p === undefined) return '—';
    if (p < 0.001) return '< 0.001';
    return p.toFixed(3);
  });

  readonly significanceLabel = computed(() => {
    const p = this.stats()?.p_value;
    if (p === null || p === undefined) return 'Not enough data';
    if (p < 0.05) return 'Statistically significant (p < 0.05)';
    return 'Not yet significant';
  });

  readonly liftPct = computed(() => {
    const s = this.stats();
    if (!s) return 0;
    if (s.a_rate === 0) return 0;
    return ((s.b_rate - s.a_rate) / s.a_rate) * 100;
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.workflowId.set(id);
      }
    });

    effect(() => {
      const id = this.workflowId();
      if (!id) return;
      this.refresh();
    });

    const timer = window.setInterval(() => {
      if (this.workflowId()) this.refresh();
    }, REFRESH_INTERVAL_MS);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  refresh(): void {
    const id = this.workflowId();
    if (!id) return;
    this.error.set(null);

    this.api
      .getABStats(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (stats) => {
          this.stats.set(stats);
          this.loadVariants(stats);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Stats unavailable.');
          this.loading.set(false);
        },
      });
  }

  private loadVariants(stats: ABStatsResponse): void {
    forkJoin({
      a: this.api.get(stats.a_workflow_id),
      b: this.api.get(stats.b_workflow_id),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ a, b }) => {
          this.aWorkflow.set(a);
          this.bWorkflow.set(b);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not load variants.');
          this.loading.set(false);
        },
      });
  }

  /**
   * Linear "rate trend" sparkline path. With only the cumulative
   * goal_runs / total_runs available today we approximate a line
   * from (0,0) to (width, rate). Replaced with real per-day series
   * once the runs aggregator exposes them.
   */
  sparklinePath(rate: number, width = 120, height = 28): string {
    const clamped = Math.max(0, Math.min(1, rate));
    const y = height - clamped * height;
    return `M 0 ${height} L ${width} ${y}`;
  }

  sparklineFill(rate: number, width = 120, height = 28): string {
    const clamped = Math.max(0, Math.min(1, rate));
    const y = height - clamped * height;
    return `M 0 ${height} L ${width} ${y} L ${width} ${height} Z`;
  }
}
