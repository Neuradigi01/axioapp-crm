import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { extractApiError } from '@core/services/api-error.util';
import {
  Contact,
  ContactCreate,
  ContactUpdate,
  ContactsApiService,
} from './contacts-api.service';

/**
 * Modal that creates or edits a `Contact`. Splits the form into two
 * sections per the master plan:
 *   - "Standard" â€” the canonical columns on the contacts row
 *     (full_name, phone, email, source, tags).
 *   - "Custom"   â€” the dynamic block driven by
 *     `GET /custom-fields/contact/render`, rendered through
 *     `<app-dynamic-form>`. Nothing about custom fields is hardcoded
 *     here (rule 4).
 */
@Component({
  selector: 'app-contact-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DynamicFormComponent],
  templateUrl: './contact-form-modal.component.html',
})
export class ContactFormModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** When set, the modal opens in edit mode. Null â†’ create mode. */
  @Input() set contact(value: Contact | null) {
    this._contact.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Input() set submitError(value: string | null) {
    this._submitError.set(value);
  }

  @Output() readonly save = new EventEmitter<{
    create?: ContactCreate;
    update?: ContactUpdate;
  }>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _contact = signal<Contact | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _submitError = signal<string | null>(null);

  protected readonly fields = signal<FieldDef[]>([]);
  protected readonly fieldsLoading = signal(true);
  protected readonly fieldsError = signal<string | null>(null);

  protected readonly customValue = signal<FormValue>({});
  protected readonly customValid = signal(true);

  readonly isEdit = computed(() => this._contact() !== null);
  readonly submitting$ = this._submitting.asReadonly();
  readonly submitError$ = this._submitError.asReadonly();

  readonly standard = this.fb.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    phone: ['', [Validators.maxLength(32)]],
    email: ['', [Validators.email, Validators.maxLength(255)]],
    source: ['', [Validators.maxLength(64)]],
    tags_csv: [''],
  });

  ngOnInit(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => {
          this.fields.set(defs);
          this.fieldsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.fieldsError.set(
            extractApiError(err) ?? 'Could not load custom field definitions.',
          );
          this.fieldsLoading.set(false);
        },
      });

    const existing = this._contact();
    if (existing) this.resetForm(existing);
  }

  protected onCustomValueChange(v: FormValue): void {
    this.customValue.set(v);
  }

  protected onCustomValidityChange(valid: boolean): void {
    this.customValid.set(valid);
  }

  protected onSubmit(): void {
    if (this.standard.invalid) {
      this.standard.markAllAsTouched();
      return;
    }
    if (!this.customValid()) {
      // The dynamic-form's own per-field errors already surface; just
      // refuse to leave the modal open in an invalid state.
      this._submitError.set('Please fix the highlighted custom fields.');
      return;
    }
    this._submitError.set(null);

    const raw = this.standard.getRawValue();
    const payload: ContactCreate = {
      full_name: raw.full_name!.trim(),
      phone: this.nullableTrim(raw.phone),
      email: this.nullableTrim(raw.email),
      source: this.nullableTrim(raw.source),
      tags: this.parseTags(raw.tags_csv),
      custom_data: this.customValue() as Record<string, unknown>,
    };

    if (this.isEdit()) {
      this.save.emit({ update: payload });
    } else {
      this.save.emit({ create: payload });
    }
  }

  private resetForm(contact: Contact): void {
    this.standard.reset({
      full_name: contact.full_name,
      phone: contact.phone ?? '',
      email: contact.email ?? '',
      source: contact.source ?? '',
      tags_csv: contact.tags.join(', '),
    });
    this.customValue.set(contact.custom_data as FormValue);
  }

  private nullableTrim(v: string | null | undefined): string | null {
    if (v === null || v === undefined) return null;
    const trimmed = v.trim();
    return trimmed.length === 0 ? null : trimmed;
  }

  private parseTags(csv: string | null | undefined): string[] {
    if (!csv) return [];
    const seen = new Set<string>();
    for (const part of csv.split(',')) {
      const value = part.trim();
      if (value.length > 0 && !seen.has(value)) seen.add(value);
    }
    return [...seen];
  }

}
