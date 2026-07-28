/**
 * Sequence detail page (route `/user/settings/email-sequences/:id`).
 *
 * Header: sequence name + step summary (compact, e.g. "3 steps · day
 * 0 → day 2 → day 5"). Below that, an enrollment table with:
 *   - state filter chips (all / active / completed / paused_on_reply
 *     / paused_manual / cancelled),
 *   - contact id column (links nowhere yet — contact-detail page
 *     doesn't exist in the codebase),
 *   - state pill,
 *   - current step,
 *   - enrolled-at via DatePipe,
 *   - per-row actions: Pause / Resume / Cancel (state-machine aware).
 *
 * Manual permission gate: pause / resume / cancel require
 * `email.sequences.enroll`. Reps with `email.sequences.enroll` (every
 * sales role) can manage their own enrollments; backend enforces RLS.
 */
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import {
  EmailSequence,
  EmailSequencesApiService,
  Enrollment,
  EnrollmentState,
} from '../../services/email-sequences-api.service';

type StateFilter = 'all' | EnrollmentState;

@Component({
  selector: 'app-sequence-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, LucideAngularModule, RouterLink],
  templateUrl: './sequence-detail.component.html',
})
export class SequenceDetailComponent implements OnInit {
  private readonly api = inject(EmailSequencesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly sequenceId = signal<string | null>(null);

  protected readonly sequence = signal<EmailSequence | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly inlineError = signal<string | null>(null);

  protected readonly enrollments = signal<Enrollment[] | null>(null);
  protected readonly enrollmentsLoading = signal<boolean>(false);

  protected readonly stateFilter = signal<StateFilter>('all');
  /** Per-row action lock — only one in-flight per row. */
  protected readonly actingOn = signal<string | null>(null);

  protected readonly canManageEnrollments = computed(() =>
    this.auth.hasPermission('email.sequences.enroll'),
  );

  protected readonly canManageSequence = computed(() =>
    this.auth.hasPermission('email.sequences.manage'),
  );

  protected readonly stepSummary = computed(() => {
    const s = this.sequence();
    if (!s) return '';
    if (s.steps.length === 0) return 'No steps';
    return s.steps
      .map((step, i) => (i === 0 ? 'day 0' : `day ${this._cumulative(s.steps, i)}`))
      .join(' → ');
  });

  protected readonly stateOptions: ReadonlyArray<StateFilter> = [
    'all',
    'active',
    'completed',
    'paused_on_reply',
    'paused_manual',
    'cancelled',
  ];

  protected readonly stateLabels: Record<StateFilter, string> = {
    all: 'All',
    active: 'Active',
    completed: 'Completed',
    paused_on_reply: 'Paused (reply)',
    paused_manual: 'Paused',
    cancelled: 'Cancelled',
  };

  protected readonly statePillClasses: Record<EnrollmentState, string> = {
    active: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
    completed: 'bg-surface-2 text-default ring-1 border-subtle',
    paused_on_reply: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
    paused_manual: 'bg-blue-50 text-blue-700 ring-1 ring-blue-200',
    cancelled: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',
  };

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      this.sequenceId.set(id);
      if (id) {
        this._loadSequence(id);
        this._loadEnrollments(id, this.stateFilter());
      }
    });
  }

  setStateFilter(s: StateFilter): void {
    if (this.stateFilter() === s) return;
    this.stateFilter.set(s);
    const id = this.sequenceId();
    if (id) this._loadEnrollments(id, s);
  }

  pause(row: Enrollment): void {
    this._actOnEnrollment(row, 'pause');
  }

  resume(row: Enrollment): void {
    this._actOnEnrollment(row, 'resume');
  }

  cancel(row: Enrollment): void {
    if (!confirm("Cancel this enrollment? This can't be undone.")) return;
    this._actOnEnrollment(row, 'cancel');
  }

  private _actOnEnrollment(row: Enrollment, action: 'pause' | 'resume' | 'cancel'): void {
    if (this.actingOn() !== null) return;
    this.actingOn.set(row.id);
    this.inlineError.set(null);
    const op$ =
      action === 'pause'
        ? this.api.pauseEnrollment(row.id)
        : action === 'resume'
          ? this.api.resumeEnrollment(row.id)
          : this.api.cancelEnrollment(row.id);
    op$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (updated) => {
        this.actingOn.set(null);
        this.enrollments.update((rows) =>
          (rows ?? []).map((r) => (r.id === updated.id ? updated : r)),
        );
      },
      error: (err: HttpErrorResponse) => {
        this.actingOn.set(null);
        this.inlineError.set(extractApiError(err));
      },
    });
  }

  /** Cumulative delay across steps [0..i]. step_order is dense from
   *  the backend so we walk the array directly. */
  private _cumulative(steps: EmailSequence['steps'], upToIndex: number): number {
    let total = 0;
    const sorted = steps.slice().sort((a, b) => a.step_order - b.step_order);
    for (let i = 0; i <= upToIndex; i++) {
      total += sorted[i]?.delay_days ?? 0;
    }
    return total;
  }

  private _loadSequence(id: string): void {
    this.loadError.set(null);
    this.api
      .getSequence(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => this.sequence.set(row),
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err));
        },
      });
  }

  private _loadEnrollments(sequenceId: string, state: StateFilter): void {
    this.enrollmentsLoading.set(true);
    this.api
      .listEnrollments({
        sequence_id: sequenceId,
        state: state === 'all' ? undefined : state,
        size: 100,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.enrollments.set(resp.items);
          this.enrollmentsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.enrollmentsLoading.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  protected canPause(state: EnrollmentState): boolean {
    return state === 'active';
  }

  protected canResume(state: EnrollmentState): boolean {
    return state === 'paused_manual' || state === 'paused_on_reply';
  }

  protected canCancel(state: EnrollmentState): boolean {
    return state !== 'completed' && state !== 'cancelled';
  }
}
