import { CommonModule, DatePipe, JsonPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  WorkflowRunDetailResponse,
  WorkflowRunDetailStep,
  WorkflowsApiService,
} from './workflows-api.service';

/**
 * Step 19 — per-run timeline. URL: `/user/workflows/runs/:run_id`.
 *
 * Renders one row per executed step with status badge + node label +
 * started_at + duration + skip_reason / error / payload. Expand a
 * step to see the resolved payload + (where present) the
 * compliance-decision detail behind a skip.
 */

@Component({
  selector: 'app-workflow-run-detail-page',
  standalone: true,
  imports: [CommonModule, DatePipe, JsonPipe, RouterLink, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './run-detail.page.html',
})
export class WorkflowRunDetailPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly runId = signal<string>('');
  readonly detail = signal<WorkflowRunDetailResponse | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly expandedStep = signal<string | null>(null);

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((p) => {
      const id = p.get('run_id');
      if (id) this.runId.set(id);
    });

    effect(() => {
      const id = this.runId();
      if (!id) return;
      this.refresh(id);
    });
  }

  refresh(runId: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getRunDetail(runId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.detail.set(resp);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Run unavailable.');
          this.loading.set(false);
        },
      });
  }

  toggleStep(stepId: string): void {
    this.expandedStep.update((c) => (c === stepId ? null : stepId));
  }

  durationLabel(step: WorkflowRunDetailStep): string {
    if (!step.completed_at) return '—';
    const start = new Date(step.started_at).getTime();
    const end = new Date(step.completed_at).getTime();
    const ms = end - start;
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
    return `${(ms / 60_000).toFixed(1)} min`;
  }

  statusClasses(status: string): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-100 text-emerald-800';
      case 'skipped':
        return 'bg-amber-100 text-amber-800';
      case 'errored':
        return 'bg-rose-100 text-rose-800';
      case 'running':
        return 'bg-sky-100 text-sky-800';
      case 'paused':
        return 'bg-amber-100 text-amber-800';
      case 'canceled':
        return 'bg-zinc-200 text-zinc-700';
      default:
        return 'bg-zinc-100 text-zinc-700';
    }
  }
}
