import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { InrPipe } from '../../shared/pipes/inr.pipe';
import { extractApiError } from '@core/services/api-error.util';
import { StaffApiService, StaffWithPerformance } from '../staff-api.service';

/**
 * Targets & Commission tab — table of staff with an inline editor.
 *
 * Click "Edit" on a row → that row expands with three numeric inputs
 * (commission %, monthly target â‚¹, rating). Hitting Save fires PUT
 * /staff/{user_id} and emits `saved` so the parent reloads the joined
 * list.
 *
 * Only one row is editable at a time — picking another row collapses
 * the previous one.
 */
@Component({
  selector: 'app-staff-targets-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, InrPipe],
  templateUrl: './targets.component.html',
})
export class StaffTargetsTabComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder);

  readonly rows = input.required<StaffWithPerformance[]>();
  @Output() readonly saved = new EventEmitter<void>();

  protected readonly editingId = signal<string | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly form = this.fb.group({
    commission_rate: this.fb.control('0', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    monthly_target: this.fb.control('0', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    rating: this.fb.control('0', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    employment_status: this.fb.control<'active' | 'leave' | 'terminated'>('active', {
      nonNullable: true,
    }),
  });

  protected startEdit(row: StaffWithPerformance): void {
    this.submitError.set(null);
    this.form.reset({
      commission_rate: row.performance.commission_rate ?? '0',
      monthly_target: row.performance.monthly_target ?? '0',
      rating: row.performance.rating ?? '0',
      employment_status: row.staff.employment_status ?? 'active',
    });
    this.editingId.set(row.staff.id);
  }

  protected cancelEdit(): void {
    this.editingId.set(null);
    this.submitError.set(null);
  }

  protected save(userId: string): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const v = this.form.getRawValue();
    this.api
      .upsertProfile(userId, {
        commission_rate: v.commission_rate,
        monthly_target: v.monthly_target,
        rating: v.rating,
        employment_status: v.employment_status,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.editingId.set(null);
          this.saved.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not save profile.');
        },
      });
  }
}
