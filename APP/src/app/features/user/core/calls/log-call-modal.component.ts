import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import {
  Call,
  CallOutcome,
  CallsApiService,
} from './calls-api.service';

/**
 * Modal to log a phone call. Reused by:
 *   - Logs tab (admin types from scratch).
 *   - Phone Book tab (click-to-call pre-fills `contact_id` + phone).
 *
 * `outcomes` is passed in by the parent (loaded once and shared) so we
 * don't refetch on every modal open.
 */
@Component({
  selector: 'app-log-call-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './log-call-modal.component.html',
})
export class LogCallModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() outcomes: CallOutcome[] = [];
  /** Pre-fill the contact id (used by Phone Book's click-to-call). */
  @Input() set prefilledContactId(value: string | null) {
    if (value) {
      this.form.patchValue({ contact_id: value });
    }
  }
  /** Read-only label rendered if `prefilledContactId` is set. */
  @Input() prefilledContactName: string | null = null;

  @Output() readonly saved = new EventEmitter<Call>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly form = this.fb.group({
    contact_id: this.fb.control<string | null>(null),
    direction: this.fb.control<'in' | 'out'>('out', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    started_at: this.fb.control(this._nowIso(), {
      nonNullable: true,
      validators: [Validators.required],
    }),
    duration_sec: this.fb.control(60, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(0)],
    }),
    outcome_id: this.fb.control<string | null>(null),
    notes: this.fb.control<string | null>(null),
  });

  protected save(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const v = this.form.getRawValue();
    this.api
      .createCall({
        contact_id: v.contact_id ?? null,
        direction: v.direction,
        started_at: new Date(v.started_at).toISOString(),
        duration_sec: v.duration_sec,
        outcome_id: v.outcome_id ?? null,
        notes: v.notes ?? null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (call) => {
          this.submitting.set(false);
          this.saved.emit(call);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(this._extract(err) ?? 'Could not log call.');
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }

  private _nowIso(): string {
    // datetime-local input wants `YYYY-MM-DDTHH:mm` (no seconds, no TZ)
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
