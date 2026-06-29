import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  WorkflowRunRead,
  WorkflowStepRunRead,
  WorkflowsApiService,
} from './workflows-api.service';

/**
 * Right-anchored side drawer that lists the most recent runs of a
 * single workflow. Wraps the Step-4 endpoints
 * `GET /workflows/{id}/runs` and `GET /workflows/runs/{id}/steps`.
 *
 * Each row collapses by default; click to expand the ordered step
 * timeline for that run. Step 19 will swap the static counts on the
 * parent page for richer charts; the drawer here stays a "what happened
 * to this contact" inspector.
 */

const PAGE_SIZE = 50;


@Component({
  selector: 'app-workflow-run-history-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DatePipe, LucideAngularModule],
  templateUrl: './run-history-drawer.component.html',
})
export class RunHistoryDrawerComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Opening the drawer with a workflow id triggers a fetch.
   *  Null closes the drawer (parent passes null to dismiss). */
  readonly workflowId = input<string | null>(null);
  readonly workflowName = input<string | null>(null);

  readonly closed = output<void>();

  protected readonly runs = signal<WorkflowRunRead[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly expandedRunId = signal<string | null>(null);
  protected readonly steps = signal<WorkflowStepRunRead[]>([]);
  protected readonly stepsLoading = signal<boolean>(false);
  protected readonly stepsError = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.workflowId();
      if (!id) {
        this.runs.set([]);
        this.expandedRunId.set(null);
        this.steps.set([]);
        return;
      }
      this.fetchRuns(id);
    });
  }

  protected close(): void {
    this.closed.emit();
  }

  protected toggleRow(run: WorkflowRunRead): void {
    if (this.expandedRunId() === run.id) {
      this.expandedRunId.set(null);
      this.steps.set([]);
      return;
    }
    this.expandedRunId.set(run.id);
    this.fetchSteps(run.id);
  }

  protected isExpanded(runId: string): boolean {
    return this.expandedRunId() === runId;
  }

  protected statusClasses(status: string): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'running':
        return 'bg-blue-50 text-blue-700 ring-blue-200';
      case 'paused':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      case 'errored':
        return 'bg-rose-50 text-rose-700 ring-rose-200';
      case 'canceled':
        return 'bg-zinc-100 text-zinc-500 ring-zinc-300';
      case 'pending':
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  protected stepStatusClasses(status: string): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'running':
        return 'bg-blue-50 text-blue-700 ring-blue-200';
      case 'skipped':
        return 'bg-zinc-100 text-zinc-500 ring-zinc-300';
      case 'errored':
        return 'bg-rose-50 text-rose-700 ring-rose-200';
      case 'pending':
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  protected trackRun = (_: number, row: WorkflowRunRead) => row.id;
  protected trackStep = (_: number, row: WorkflowStepRunRead) => row.id;

  private fetchRuns(workflowId: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listRuns(workflowId, { limit: PAGE_SIZE, offset: 0 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.runs.set(res.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.runs.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load run history.',
          );
        },
      });
  }

  private fetchSteps(runId: string): void {
    this.stepsLoading.set(true);
    this.stepsError.set(null);
    this.api
      .listRunSteps(runId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.steps.set(rows);
          this.stepsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.steps.set([]);
          this.stepsLoading.set(false);
          this.stepsError.set(
            extractApiError(err) ?? 'Could not load steps for this run.',
          );
        },
      });
  }
}
