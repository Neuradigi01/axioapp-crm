import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
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
      // Emit valueChanges so the toSignal mirrors (dateValue / timeValue)
      // pick up the prefilled slot. With `emitEvent: false` the signals
      // would stay at their initial '' and `canConfirm` would keep the
      // Save button disabled until the user re-touched both fields.
      this.dateControl.setValue(this.toDateInput(d));
      this.timeControl.setValue(this.toTimeInput(d));
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

  /** Today in `YYYY-MM-DD` — used as the date input's `min` so the
   *  native picker can't offer past dates at all, instead of letting
   *  the user pick one and rejecting on Save. */
  protected readonly todayDate = signal(this.toDateInput(new Date()));

  /** Reactive mirrors of the form controls' values. Signals are
   *  required because `dateControl.value` is a plain accessor and
   *  won't invalidate a `computed` when the user types. Without
   *  these, `crossFieldError`/`canConfirm` would run once at open
   *  and freeze — e.g. the "matches the current slot" error would
   *  persist after the user changed the time. */
  private readonly dateValue = toSignal(this.dateControl.valueChanges, {
    initialValue: this.dateControl.value,
  });
  private readonly timeValue = toSignal(this.timeControl.valueChanges, {
    initialValue: this.timeControl.value,
  });

  /** When the selected date is today, `min` on the time input is the
   *  current `HH:MM` so users can't pick a slot earlier today. On any
   *  future date the constraint is removed. */
  protected readonly minTimeForSelectedDate = computed<string | null>(() => {
    const selected = this.dateValue();
    if (selected !== this.todayDate()) return null;
    return this.toTimeInput(new Date());
  });

  /** Cross-field check: the new date+time must be a valid datetime
   *  that is (a) not in the past and (b) different from the
   *  appointment's original `scheduled_at`. */
  protected readonly crossFieldError = computed<string | null>(() => {
    const d = this.dateValue();
    const t = this.timeValue();
    if (!d || !t) return null;
    const parsed = new Date(`${d}T${t}`);
    if (Number.isNaN(parsed.getTime())) return null;
    // 5-min grace covers clock skew, matches `dateNotPastValidator`.
    if (parsed.getTime() + 5 * 60 * 1000 < Date.now()) {
      return 'Pick a future date and time — the selected slot is already in the past.';
    }
    const original = this._appointment()?.scheduled_at;
    if (original && parsed.getTime() === new Date(original).getTime()) {
      return 'Pick a different time — this matches the current slot.';
    }
    return null;
  });

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    if (!this.dateValue() || !this.timeValue()) return false;
    if (this.reasonControl.invalid) return false;
    return this.crossFieldError() === null;
  });

  /** Human-readable label for the appointment's original slot, shown
   *  in the modal header so the rep can see what they're changing
   *  from — e.g. `04 Aug 2026, 10:00`. */
  protected readonly currentSlotLabel = computed<string>(() => {
    const a = this._appointment();
    if (!a) return '';
    const d = new Date(a.scheduled_at);
    if (Number.isNaN(d.getTime())) return '';
    const day = String(d.getDate()).padStart(2, '0');
    const month = d.toLocaleString('en', { month: 'short' });
    const year = d.getFullYear();
    return `${day} ${month} ${year}, ${this.toTimeInput(d)}`;
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
