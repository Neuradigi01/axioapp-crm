import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  effect,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';

import { commonValidators } from '../../shared/validators';

/**
 * Payload emitted on confirm. Mirrors the backend's `MoveStageRequest`
 * lost-reason fields exactly so the parent can pass it straight through.
 */
export interface LostReasonConfirm {
  lost_reason: 'price' | 'timing' | 'competitor' | 'no_response' | 'other';
  lost_reason_other: string | null;
}

/**
 * Lost-reason picker. Triggered any time the user moves a lead into a
 * `is_lost=true` stage — from the kanban drag-to-Lost, the move-stage
 * button on a card, or a future bulk-move-stage flow.
 *
 * The backend (`move_stage_for_lead`) rejects a Lost transition without
 * a `lost_reason`. This modal collects it and the parent re-issues the
 * move-stage call with the reason attached.
 *
 * Picklist matches `LOST_REASONS` in `core/leads/schemas.py` and the
 * `ck_leads_lost_reason_picklist` DB CHECK constraint. Drift between
 * the two would surface as a 422 from the backend — keep them in sync.
 */
@Component({
  selector: 'app-lost-reason-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './lost-reason-modal.component.html',
})
export class LostReasonModalComponent {
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set submitting(v: boolean) {
    this._submitting.set(v);
  }

  @Input() set error(v: string | null) {
    this._error.set(v);
  }

  @Input() set currentReason(v: string | null) {
    if (v) this.reasonControl.setValue(v, { emitEvent: false });
  }

  @Input() set currentReasonOther(v: string | null) {
    if (v) this.otherControl.setValue(v, { emitEvent: false });
  }

  @Output() readonly confirm = new EventEmitter<LostReasonConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  protected readonly otherControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [commonValidators.maxLength(500)],
  });

  /** Tracks the reason value so `otherRequired` + `canConfirm` react to
   * radio changes (a plain `FormControl.value` read inside a `computed`
   * does not fire — signals need a source that emits on change).
   */
  private readonly reasonValue = toSignal(this.reasonControl.valueChanges, {
    initialValue: this.reasonControl.value,
  });
  private readonly otherValue = toSignal(this.otherControl.valueChanges, {
    initialValue: this.otherControl.value,
  });

  protected readonly reasons = [
    { v: 'price', label: 'Price' },
    { v: 'timing', label: 'Timing' },
    { v: 'competitor', label: 'Competitor' },
    { v: 'no_response', label: 'No response' },
    { v: 'other', label: 'Other' },
  ] as const;

  /** Pre-emptive guard for the "Other → must type" UX. */
  protected readonly otherRequired = computed(() => this.reasonValue() === 'other');

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    if (this.reasonControl.invalid) return false;
    if (this.otherRequired() && !(this.otherValue() ?? '').trim()) return false;
    if (this.otherControl.invalid) return false;
    return true;
  });

  constructor() {
    // Layer `required` on the free-text control only when reason === 'other'.
    effect(() => {
      const isOther = this.otherRequired();
      const base = [commonValidators.maxLength(500)];
      this.otherControl.setValidators(isOther ? [Validators.required, ...base] : base);
      this.otherControl.updateValueAndValidity({ emitEvent: false });
    });
  }

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    this.confirm.emit({
      lost_reason: this.reasonControl.value as LostReasonConfirm['lost_reason'],
      lost_reason_other:
        this.reasonControl.value === 'other' ? this.otherControl.value.trim() : null,
    });
  }
}
