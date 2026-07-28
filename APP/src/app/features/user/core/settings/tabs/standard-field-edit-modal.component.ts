import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { extractApiError } from '@core/services/api-error.util';

import { StandardFieldsApiService } from '../../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../../standard-fields/standard-fields-signals.service';
import type {
  OverridableProp,
  StandardFieldOverrideIn,
  StandardFieldRendered,
} from '../../standard-fields/types';

/**
 * Edit one standard field's overrides. The form is built dynamically from
 * `field.overridable_props` — controls for locked knobs are rendered
 * disabled with the registry default value so the user can see what
 * they can't change.
 *
 * Submission strategy: build a payload of *only* the props the user
 * actually touched (diff against the originally-rendered values). This
 * keeps the PUT body tight and lets the backend's per-field validator
 * (Step 2 service.py) work against exactly what changed.
 */
type FormShape = {
  label: FormControl<string | null>;
  placeholder: FormControl<string | null>;
  help_text: FormControl<string | null>;
  is_required: FormControl<boolean | null>;
  is_hidden: FormControl<boolean | null>;
  min_value: FormControl<number | null>;
  max_value: FormControl<number | null>;
  step_value: FormControl<number | null>;
  display_order: FormControl<number | null>;
};

const PAYLOAD_BY_PROP: Record<OverridableProp, keyof StandardFieldOverrideIn> = {
  label: 'label',
  placeholder: 'placeholder',
  help: 'help_text',
  required: 'is_required',
  hidden: 'is_hidden',
  min: 'min_value',
  max: 'max_value',
  step: 'step_value',
  display_order: 'display_order',
};

@Component({
  selector: 'app-standard-field-edit-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './standard-field-edit-modal.component.html',
})
export class StandardFieldEditModalComponent {
  private readonly api = inject(StandardFieldsApiService);
  private readonly signals = inject(StandardFieldsSignalsService);

  /** The field being edited. Set once when the modal opens. */
  @Input({ required: true }) set field(value: StandardFieldRendered) {
    this._field.set(value);
    this.resetForm(value);
  }

  @Output() readonly saved = new EventEmitter<void>();
  @Output() readonly cancel = new EventEmitter<void>();
  @Output() readonly didReset = new EventEmitter<void>();

  protected readonly _field = signal<StandardFieldRendered | null>(null);
  protected readonly saving = signal(false);
  protected readonly resetting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  readonly form = new FormGroup<FormShape>({
    label: new FormControl<string | null>(null, [Validators.maxLength(128)]),
    placeholder: new FormControl<string | null>(null, [Validators.maxLength(255)]),
    help_text: new FormControl<string | null>(null, [Validators.maxLength(500)]),
    is_required: new FormControl<boolean | null>(null),
    is_hidden: new FormControl<boolean | null>(null),
    min_value: new FormControl<number | null>(null),
    max_value: new FormControl<number | null>(null),
    step_value: new FormControl<number | null>(null),
    display_order: new FormControl<number | null>(null, [Validators.min(0), Validators.max(999)]),
  });

  /** Convenience for the template — case-by-case `@if` is faster to read
   *  than `field()?.overridable_props.includes('label')` repeated nine times. */
  readonly canEdit = computed(() => {
    const f = this._field();
    if (!f) return null;
    const set = new Set(f.overridable_props);
    return {
      label: set.has('label'),
      placeholder: set.has('placeholder'),
      help_text: set.has('help'),
      is_required: set.has('required'),
      is_hidden: set.has('hidden'),
      min_value: set.has('min'),
      max_value: set.has('max'),
      step_value: set.has('step'),
      display_order: set.has('display_order'),
    };
  });

  readonly hidingLockedWarning = computed(() => {
    const f = this._field();
    return f !== null && f.backend_required && !f.is_hidden;
  });

  /** Show the "Reset" button only when an override actually exists. */
  readonly canReset = computed(() => this._field()?.is_overridden ?? false);

  private resetForm(value: StandardFieldRendered): void {
    // Disable controls for props not in `overridable_props` so the
    // backend's 422 path is impossible to hit from this UI. We still
    // show them in the template (read-only) so the user sees the
    // registry default for the locked knob.
    const allowed = new Set(value.overridable_props);
    type Pair = [keyof FormShape, OverridableProp];
    const pairs: Pair[] = [
      ['label', 'label'],
      ['placeholder', 'placeholder'],
      ['help_text', 'help'],
      ['is_required', 'required'],
      ['is_hidden', 'hidden'],
      ['min_value', 'min'],
      ['max_value', 'max'],
      ['step_value', 'step'],
      ['display_order', 'display_order'],
    ];

    this.form.reset({
      label: value.label,
      placeholder: value.placeholder,
      help_text: value.help_text,
      is_required: value.is_required,
      is_hidden: value.is_hidden,
      min_value: value.min_value,
      max_value: value.max_value,
      step_value: value.step_value,
      display_order: value.display_order,
    });

    for (const [ctrl, prop] of pairs) {
      const control = this.form.get(ctrl)!;
      if (allowed.has(prop)) {
        control.enable({ emitEvent: false });
      } else {
        control.disable({ emitEvent: false });
      }
    }
  }

  protected onSubmit(): void {
    const f = this._field();
    if (!f || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const payload = this.buildDiff(f);
    if (Object.keys(payload).length === 0) {
      this.cancel.emit();
      return;
    }
    this.saving.set(true);
    this.submitError.set(null);
    this.api.upsert(f.entity, f.field_key, payload).subscribe({
      next: () => {
        this.saving.set(false);
        this.signals.notifyChange();
        this.saved.emit();
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.submitError.set(extractApiError(err) ?? 'Save failed.');
      },
    });
  }

  protected onReset(): void {
    const f = this._field();
    if (!f) return;
    this.resetting.set(true);
    this.submitError.set(null);
    this.api.reset(f.entity, f.field_key).subscribe({
      next: () => {
        this.resetting.set(false);
        this.signals.notifyChange();
        this.didReset.emit();
      },
      error: (err: HttpErrorResponse) => {
        this.resetting.set(false);
        this.submitError.set(extractApiError(err) ?? 'Reset failed.');
      },
    });
  }

  /** Compare each enabled control against the as-rendered value. Only
   *  changed entries land in the payload, mapped to backend column names. */
  private buildDiff(field: StandardFieldRendered): StandardFieldOverrideIn {
    const out: StandardFieldOverrideIn = {};
    const raw = this.form.getRawValue();

    const compare = <K extends keyof FormShape>(
      ctrl: K,
      original: StandardFieldRendered[Extract<K, keyof StandardFieldRendered>],
    ): void => {
      if (this.form.controls[ctrl].disabled) return;
      const current = raw[ctrl];
      if (current === original) return;
      const prop = ((): OverridableProp | null => {
        // Map FormShape key → OverridableProp token.
        switch (ctrl) {
          case 'label':
            return 'label';
          case 'placeholder':
            return 'placeholder';
          case 'help_text':
            return 'help';
          case 'is_required':
            return 'required';
          case 'is_hidden':
            return 'hidden';
          case 'min_value':
            return 'min';
          case 'max_value':
            return 'max';
          case 'step_value':
            return 'step';
          case 'display_order':
            return 'display_order';
          default:
            return null;
        }
      })();
      if (prop === null) return;
      const backendKey = PAYLOAD_BY_PROP[prop];
      (out[backendKey] as unknown) = current;
    };

    compare('label', field.label);
    compare('placeholder', field.placeholder);
    compare('help_text', field.help_text);
    compare('is_required', field.is_required);
    compare('is_hidden', field.is_hidden);
    compare('min_value', field.min_value);
    compare('max_value', field.max_value);
    compare('step_value', field.step_value);
    compare('display_order', field.display_order);

    return out;
  }
}
