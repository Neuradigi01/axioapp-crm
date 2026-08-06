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

import { ScheduleConfigModalComponent } from './schedule-config-modal.component';

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
  imports: [CommonModule, DatePipe, LucideAngularModule, ScheduleConfigModalComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './schedules-drawer.component.html',
})
export class SchedulesDrawerComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly workflowId = input.required<string>();
  readonly defaultTimezone = input<string>('UTC');

  readonly close = output<void>();

  readonly schedules = signal<Schedule[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly deletingId = signal<string | null>(null);

  readonly modalOpen = signal(false);
  readonly editingSchedule = signal<Schedule | null>(null);

  constructor() {
    effect(() => {
      const id = this.workflowId();
      if (!id) return;
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
    this.editingSchedule.set(null);
    this.modalOpen.set(true);
  }

  openEdit(s: Schedule): void {
    this.editingSchedule.set(s);
    this.modalOpen.set(true);
  }

  closeModal(): void {
    this.modalOpen.set(false);
    this.editingSchedule.set(null);
  }

  onSaved(saved: Schedule): void {
    // Merge into the list — replace when editing, prepend when
    // creating. Then close the modal.
    const existing = this.schedules().find((s) => s.id === saved.id);
    if (existing) {
      this.schedules.set(this.schedules().map((s) => (s.id === saved.id ? saved : s)));
    } else {
      this.schedules.set([...this.schedules(), saved]);
    }
    this.closeModal();
  }

  onDelete(s: Schedule): void {
    const proceed = confirm(
      `Delete schedule "${s.name}"? Its history stays but no future fires will happen.`,
    );
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
