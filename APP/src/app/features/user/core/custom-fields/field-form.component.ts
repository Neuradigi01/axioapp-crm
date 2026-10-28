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
import { toSignal } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';

import {
  CustomField,
  CustomFieldCreate,
  CustomFieldUpdate,
  FieldType,
} from './custom-fields-api.service';

const FIELD_TYPES: ReadonlyArray<{ value: FieldType; label: string }> = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'select', label: 'Select (single choice)' },
  { value: 'multiselect', label: 'Multi-select' },
  { value: 'date', label: 'Date' },
  { value: 'datetime', label: 'Date & time' },
  { value: 'boolean', label: 'Yes / No' },
  { value: 'phone', label: 'Phone' },
  { value: 'email', label: 'Email' },
  { value: 'currency', label: 'Currency (INR)' },
];

const FIELD_KEY_RE = /^[a-z][a-z0-9_]{1,49}$/;

function fieldKeyValidator(c: AbstractControl): ValidationErrors | null {
  return FIELD_KEY_RE.test(c.value) ? null : { fieldKey: true };
}

@Component({
  selector: 'app-field-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './field-form.component.html',
})
export class FieldFormComponent {
  private readonly fb = inject(FormBuilder);

  readonly fieldTypes = FIELD_TYPES;

  /** When set, the form switches into edit mode (field_key locked). */
  @Input() set field(value: CustomField | null) {
    this._field.set(value);
    this.resetForm(value);
  }

  /** Required to submit a new field; bound by the parent page. */
  @Input({ required: true }) entityType!: string;

  /** Server-side validation message (relayed from API 4xx). */
  @Input() set submitError(value: string | null) {
    this._submitError.set(value);
  }

  /** Disable the submit button while the parent is in-flight. */
  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Output() readonly save = new EventEmitter<{
    create?: CustomFieldCreate;
    update?: CustomFieldUpdate;
  }>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _field = signal<CustomField | null>(null);
  protected readonly _submitError = signal<string | null>(null);
  protected readonly _submitting = signal(false);

  readonly isEdit = computed(() => this._field() !== null);
  readonly submitError$ = this._submitError.asReadonly();
  readonly submitting$ = this._submitting.asReadonly();

  readonly form = this.fb.group({
    field_key: ['', [Validators.required, fieldKeyValidator]],
    field_label: ['', [Validators.required, Validators.maxLength(128)]],
    field_type: this.fb.control<FieldType>('text', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    is_required: [false],
    is_hidden: [false],
    choices_csv: [''],
  });

  // toSignal() converts the form-control's valueChanges Observable into a
  // signal so the `needsChoices` computed re-evaluates whenever the user
  // picks a different type from the dropdown. Without this the computed
  // never re-runs (plain `.value` accessor isn't a signal dependency).
  private readonly fieldTypeSig = toSignal(this.form.controls.field_type.valueChanges, {
    initialValue: this.form.controls.field_type.value,
  });

  readonly needsChoices = computed(() => {
    const t = this.fieldTypeSig();
    return t === 'select' || t === 'multiselect';
  });

  private resetForm(value: CustomField | null): void {
    if (value === null) {
      this.form.reset({
        field_key: '',
        field_label: '',
        field_type: 'text',
        is_required: false,
        is_hidden: false,
        choices_csv: '',
      });
      this.form.controls.field_key.enable();
      this.form.controls.field_type.enable();
      return;
    }
    this.form.reset({
      field_key: value.field_key,
      field_label: value.field_label,
      field_type: value.field_type,
      is_required: value.is_required,
      is_hidden: value.is_hidden,
      choices_csv: (value.options?.choices ?? []).join(', '),
    });
    // field_key + field_type are immutable on existing rows.
    this.form.controls.field_key.disable();
    this.form.controls.field_type.disable();
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const choices =
      v.field_type === 'select' || v.field_type === 'multiselect'
        ? this.parseChoices(v.choices_csv)
        : null;
    if (
      (v.field_type === 'select' || v.field_type === 'multiselect') &&
      (!choices || choices.length === 0)
    ) {
      this._submitError.set('Choices are required for select / multi-select.');
      return;
    }
    const existing = this._field();
    if (existing === null) {
      this.save.emit({
        create: {
          entity_type: this.entityType,
          field_key: v.field_key!,
          field_label: v.field_label!,
          field_type: v.field_type,
          is_required: v.is_required ?? false,
          is_hidden: v.is_hidden ?? false,
          options: choices ? { choices } : null,
        },
      });
      return;
    }
    // Edit mode: only label, required, hidden, options change.
    const update: CustomFieldUpdate = {
      field_label: v.field_label!,
      is_required: v.is_required ?? false,
      is_hidden: v.is_hidden ?? false,
    };
    if (choices) {
      update.options = { choices };
    }
    this.save.emit({ update });
  }

  private parseChoices(csv: string | null | undefined): string[] {
    if (!csv) return [];
    return csv
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }
}
