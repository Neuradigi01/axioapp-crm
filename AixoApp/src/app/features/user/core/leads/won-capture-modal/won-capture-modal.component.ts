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

import { commonValidators } from '../../shared/validators';

/**
 * Payload emitted on confirm. Mirrors the backend's `MoveStageRequest`
 * won-capture fields so the parent can pass it straight through to
 * `POST /leads/{id}/move-stage` (or `bulk-move-stage`).
 *
 * All three fields are optional at the API layer — the modal lets a
 * rep skip fields they don't know, but nudges them to fill in
 * ``won_value`` because it's the highest-ROI reporting number.
 */
export interface WonCaptureConfirm {
  won_value: string | null;
  close_date: string | null;
  won_reason: string | null;
}

/**
 * Won-capture picker. Symmetric to `LostReasonModalComponent` — fires
 * on any move-to-Won so the rep records:
 *
 *   * ``won_value`` — actual closed amount (may differ from ``budget``)
 *   * ``close_date`` — actual close date (defaults to today)
 *   * ``won_reason`` — free-text or lightweight picklist for close
 *     reporting; kept unstructured for now (unlike lost_reason) so
 *     orgs can experiment before we lock a picklist.
 *
 * The backend accepts every field as optional, so a rep can hit
 * "Skip and mark won" if they need to unclick a mis-drag; the modal
 * still records the transition + stamps ``won_at``.
 */
@Component({
  selector: 'app-won-capture-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './won-capture-modal.component.html',
})
export class WonCaptureModalComponent {
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set submitting(v: boolean) {
    this._submitting.set(v);
  }

  @Input() set error(v: string | null) {
    this._error.set(v);
  }

  /** Seed the value input with the lead's `budget` so the rep only
   *  has to change it when the closed amount differs — the common
   *  case is "won for the budgeted amount". */
  @Input() set suggestedValue(v: string | null) {
    if (v && !this.valueControl.value) {
      this.valueControl.setValue(v, { emitEvent: false });
    }
  }

  /** ISO code for the money-input label. Defaults to org currency
   *  passed in by the parent. */
  @Input() currency: string = 'INR';

  @Output() readonly confirm = new EventEmitter<WonCaptureConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly valueControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.pattern(/^\d+(\.\d{1,2})?$/)],
  });
  // Default close_date to today so the rep only edits if the close
  // was earlier / later than "now". Actual-close is a past-or-today
  // event — future closes don't make sense (that's `expected_close_date`
  // on the lead form). `dateNotFuture` allows today + past.
  protected readonly closeDateControl = new FormControl<string>(
    new Date().toISOString().slice(0, 10),
    {
      nonNullable: true,
      validators: [commonValidators.isoDate, commonValidators.dateNotFuture],
    },
  );
  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [commonValidators.maxLength(64)],
  });

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    // Value is optional at the API layer, but if the rep started
    // typing it, must parse as a valid decimal.
    if (this.valueControl.invalid) return false;
    // Close-date defaults to today; if the rep edits it, it must be a
    // valid past-or-today ISO date.
    if (this.closeDateControl.invalid) return false;
    return true;
  });

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    // Optimistically flip `_submitting` BEFORE the emit so a
    // rapid-fire double click is dropped at this component (before
    // the parent's re-render can echo `[submitting]="true"` back).
    // Prevents the double-request that used to re-stamp
    // `won_value`/`close_date` if the operator hit Confirm twice.
    this._submitting.set(true);
    const val = this.valueControl.value.trim();
    const date = this.closeDateControl.value.trim();
    const reason = this.reasonControl.value.trim();
    this.confirm.emit({
      won_value: val ? val : null,
      close_date: date ? date : null,
      won_reason: reason ? reason : null,
    });
  }

  protected onSkip(): void {
    // Rep didn't want to fill anything — still fire so the move-stage
    // request goes out (with null fields). Backend will stamp
    // ``won_at`` and mark the lead won.
    if (this._submitting()) return;
    this._submitting.set(true);
    this.confirm.emit({ won_value: null, close_date: null, won_reason: null });
  }
}
