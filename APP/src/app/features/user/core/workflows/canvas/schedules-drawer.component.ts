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

import { Schedule, WorkflowsApiService } from '../workflows-api.service';
import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';

/**
 * Right-side drawer for the workflow canvas — lists schedules
 * attached to the current workflow. Add button opens the config
 * modal in create mode; each row has Edit + Delete affordances.
 *
 * Pause / Resume + list-page surfacing land in Step 5 — deliberately
 * scoped out of Step 4 per the plan.
 */

@Component({
  selector: 'app-schedules-drawer',
  standalone: true,
  imports: [CommonModule, DatePipe, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './schedules-drawer.component.html',
})
export class SchedulesDrawerComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly confirmDialog = inject(ConfirmDialogService);

  readonly workflowId = input.required<string>();
  readonly defaultTimezone = input<string>('UTC');
  /** Ticks up when the parent finishes a save; drawer re-fetches. */
  readonly refreshToken = input<number>(0);

  readonly close = output<void>();
  /** Emit when the operator wants to create or edit a schedule.
   *  Parent (workflow-canvas.page) mounts the modal at the top level
   *  so `position: fixed` inside it is viewport-relative (the aside
   *  container uses `transform`, which would otherwise trap fixed
   *  positioning to the drawer's 440px width). */
  readonly openConfig = output<Schedule | null>();

  readonly schedules = signal<Schedule[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly deletingId = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.workflowId();
      if (!id) return;
      // Re-fetch on workflow change AND when the parent bumps
      // ``refreshToken`` (after a save closes the modal).
      const _ = this.refreshToken();
      void _;
      this.fetch();
    });
  }

  fetch(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .listSchedulesForWorkflow(this.workflowId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.schedules.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load schedules.');
        },
      });
  }

  openAdd(): void {
    this.openConfig.emit(null);
  }

  openEdit(s: Schedule): void {
    this.openConfig.emit(s);
  }

  async onDelete(s: Schedule): Promise<void> {
    const proceed = await this.confirmDialog.ask({
      title: `Delete schedule "${s.name}"?`,
      body: 'Its run history is preserved, but no future fires will happen.',
      confirmLabel: 'Delete schedule',
      danger: true,
    });
    if (!proceed) return;
    this.deletingId.set(s.id);
    this.api
      .deleteSchedule(s.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deletingId.set(null);
          this.schedules.set(this.schedules().filter((row) => row.id !== s.id));
        },
        error: (err: HttpErrorResponse) => {
          this.deletingId.set(null);
          this.error.set(extractApiError(err) ?? 'Could not delete schedule.');
        },
      });
  }

  statusBadge(s: Schedule): { label: string; klass: string } {
    if (s.active) {
      return {
        label: 'Active',
        klass: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30',
      };
    }
    const naturalExhaustion = new Set(['ended', 'max_runs', 'end_at']);
    if (s.deactivation_reason && naturalExhaustion.has(s.deactivation_reason)) {
      return {
        label: 'Ended',
        klass: 'bg-zinc-500/10 text-zinc-500 border-zinc-500/30',
      };
    }
    return {
      label: 'Paused',
      klass: 'bg-amber-500/10 text-amber-500 border-amber-500/30',
    };
  }
}
