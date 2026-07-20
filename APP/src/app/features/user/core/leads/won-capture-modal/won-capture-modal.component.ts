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
  // was earlier / later than "now".
  protected readonly closeDateControl = new FormControl<string>(
    new Date().toISOString().slice(0, 10),
    { nonNullable: true },
  );
  protected readonly reasonControl = new FormControl<string>('', { nonNullable: true });

  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    // Value is optional at the API layer, but if the rep started
    // typing it, must parse as a valid decimal.
    return this.valueControl.valid;
  });

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
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
    this.confirm.emit({ won_value: null, close_date: null, won_reason: null });
  }
}
