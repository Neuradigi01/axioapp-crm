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
    validators: [Validators.required],
  });
  protected readonly timeControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    return Boolean(this.dateControl.value && this.timeControl.value);
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
