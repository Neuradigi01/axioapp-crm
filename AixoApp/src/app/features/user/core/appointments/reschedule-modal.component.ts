import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';

import { commonValidators } from '../shared/validators';
import { Appointment } from './appointments-api.service';

/**
 * Reschedule modal — focused date / time picker plus an optional
 * "reason" textarea. The full edit form is overkill for this hot
 * path (rep on a call moving a slot 30 minutes); this component
 * gives a fast two-input flow.
 *
 * Emits `{ scheduledAt, reason }` on confirm. Parent owns the API
 * call so a single conflict-409 surfaces back here via `error`.
 */
export interface RescheduleConfirm {
  scheduledAt: string;
  reason: string | null;
}

@Component({
  selector: 'app-reschedule-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './reschedule-modal.component.html',
})
export class RescheduleModalComponent {
  protected readonly _appointment = signal<Appointment | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set appointment(value: Appointment | null) {
    this._appointment.set(value);
    if (value) {
      const d = new Date(value.scheduled_at);
      this.dateControl.setValue(this.toDateInput(d), { emitEvent: false });
      this.timeControl.setValue(this.toTimeInput(d), { emitEvent: false });
    }
  }

  @Input() set submitting(v: boolean) {
    this._submitting.set(v);
  }

  @Input() set error(v: string | null) {
    this._error.set(v);
  }

  @Output() readonly confirm = new EventEmitter<RescheduleConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly dateControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required, commonValidators.isoDate],
  });
  protected readonly timeControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [commonValidators.maxLength(500)],
  });

  /** Cross-field check: the new date+time must be a valid ISO datetime that is
   *  (a) not in the past and (b) different from the appointment's original
   *  `scheduled_at`. Surfaces messages via `crossFieldError()` so the
   *  template can show one line under the fields. */
  protected readonly crossFieldError = computed<string | null>(() => {
    const d = this.dateControl.value;
    const t = this.timeControl.value;
    if (!d || !t) return null;
    const parsed = new Date(`${d}T${t}`);
    if (Number.isNaN(parsed.getTime())) return null;
    // 5-min grace covers clock skew, matches `dateNotPastValidator`.
    if (parsed.getTime() + 5 * 60 * 1000 < Date.now()) {
      return 'New time cannot be in the past.';
    }
    const original = this._appointment()?.scheduled_at;
    if (original && parsed.getTime() === new Date(original).getTime()) {
      return 'Pick a different time — this matches the current slot.';
    }
    return null;
  });

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    if (!this.dateControl.value || !this.timeControl.value) return false;
    if (this.reasonControl.invalid) return false;
    return this.crossFieldError() === null;
  });

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    const local = new Date(`${this.dateControl.value}T${this.timeControl.value}`);
    if (Number.isNaN(local.getTime())) return;
    const reason = this.reasonControl.value.trim();
    this.confirm.emit({
      scheduledAt: local.toISOString(),
      reason: reason.length > 0 ? reason : null,
    });
  }

  private toDateInput(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  private toTimeInput(d: Date): string {
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  }
}
