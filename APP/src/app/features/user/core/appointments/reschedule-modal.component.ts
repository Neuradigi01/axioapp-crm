import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';

import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { commonValidators } from '../shared/validators';
import { Appointment } from './appointments-api.service';

/**
 * Reschedule modal — one `<crm-mobile-datetime>` slot picker plus an
 * optional "reason" textarea. The full edit form is overkill for this
 * hot path (rep on a call moving a slot 30 minutes).
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
  imports: [ReactiveFormsModule, MobileDateTimeComponent],
  templateUrl: './reschedule-modal.component.html',
})
export class RescheduleModalComponent {
  protected readonly _appointment = signal<Appointment | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set appointment(value: Appointment | null) {
    this._appointment.set(value);
    if (value) {
      // Prefill the datetime picker with the current slot in local
      // `YYYY-MM-DDTHH:mm` shape (the mobile-datetime value contract).
      this.scheduledAtControl.setValue(this.toDateTimeInput(new Date(value.scheduled_at)));
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

  @HostListener('document:keydown.escape')
  protected requestClose(): void {
    if (!this._submitting()) this.cancel.emit();
  }

  protected readonly scheduledAtControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [commonValidators.maxLength(500)],
  });

  /** Now (local, minute precision) in `YYYY-MM-DDTHH:mm` — pinned to
   *  the picker's `[min]` so past slots are disabled in-panel. Matches
   *  the pattern used by `book-appointment-modal`. */
  protected readonly scheduledAtMin = (() => {
    const d = new Date();
    const p = (n: number): string => String(n).padStart(2, '0');
    return (
      `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
      `T${p(d.getHours())}:${p(d.getMinutes())}`
    );
  })();

  /** Reactive mirror of the datetime control — signal so `computed`
   *  re-runs when the user picks a slot (raw `.value` is a plain
   *  accessor and won't invalidate). */
  private readonly scheduledAtValue = toSignal(this.scheduledAtControl.valueChanges, {
    initialValue: this.scheduledAtControl.value,
  });

  /** Slot validity: not in the past, not identical to the current
   *  slot. Returns the message to render inline. */
  protected readonly crossFieldError = computed<string | null>(() => {
    const v = this.scheduledAtValue();
    if (!v) return null;
    const parsed = new Date(v);
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
    if (!this.scheduledAtValue()) return false;
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
    const local = new Date(this.scheduledAtControl.value);
    if (Number.isNaN(local.getTime())) return;
    const reason = this.reasonControl.value.trim();
    this.confirm.emit({
      scheduledAt: local.toISOString(),
      reason: reason.length > 0 ? reason : null,
    });
  }

  private toDateTimeInput(d: Date): string {
    const p = (n: number): string => String(n).padStart(2, '0');
    return (
      `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
      `T${p(d.getHours())}:${p(d.getMinutes())}`
    );
  }

  private toTimeInput(d: Date): string {
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  }
}
