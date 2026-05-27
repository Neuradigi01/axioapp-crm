import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { FurnitureAuthService } from '../auth/auth.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { StandardFieldsApiService } from '../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';
import {
  Contact,
  ContactCreate,
  ContactDuplicateMatch,
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
  imports: [ReactiveFormsModule, DynamicFormComponent, LucideAngularModule, RouterLink],
  templateUrl: './contact-form-modal.component.html',
})
export class ContactFormModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ContactsApiService);
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  /** User list for the Owner dropdown. */
  protected readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Live duplicate-match banner. Populated by debounced phone/email
   * watchers; the user can still save through it (legitimate cases:
   * shared household phone). */
  protected readonly duplicates = signal<ContactDuplicateMatch[]>([]);

  // Standard fields registered for the `contact` entity. The registry
  // key `tags` maps to the FormControl `tags_csv` (we store the CSV
  // string and split on submit).
  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>(
    {},
  );

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

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
    assigned_to_id: [''],
  });

  constructor() {
    // Refetch override-merged defs on Settings save/reset.
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  private refreshStdFields(): void {
    this.stdApi.render('contact').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        // Modal still works with hardcoded fallbacks.
      },
    });
  }

  /** Override-driven validators on the standard FormGroup.
   *
   * The static "shape" validators (`Validators.email`, `Validators.maxLength`)
   * are always present — they're not overridable. We layer `Validators.required`
   * on top per the org's override choice. `full_name` stays required always
   * (registry locks it).
   */
  private applyStandardValidators(
    map: Record<string, StandardFieldRendered>,
  ): void {
    // full_name — always required + max 255 (backend enforces NOT NULL).
    this.standard.controls.full_name.setValidators([
      Validators.required,
      Validators.maxLength(255),
    ]);
    this.standard.controls.full_name.updateValueAndValidity({
      emitEvent: false,
    });

    const phoneRow = map['phone'];
    const phoneV: ValidatorFn[] = [Validators.maxLength(32)];
    if (phoneRow?.is_required) phoneV.push(Validators.required);
    this.standard.controls.phone.setValidators(phoneV);
    this.standard.controls.phone.updateValueAndValidity({ emitEvent: false });

    const emailRow = map['email'];
    const emailV: ValidatorFn[] = [
      Validators.email,
      Validators.maxLength(255),
    ];
    if (emailRow?.is_required) emailV.push(Validators.required);
    this.standard.controls.email.setValidators(emailV);
    this.standard.controls.email.updateValueAndValidity({ emitEvent: false });

    const sourceRow = map['source'];
    const sourceV: ValidatorFn[] = [Validators.maxLength(64)];
    if (sourceRow?.is_required) sourceV.push(Validators.required);
    this.standard.controls.source.setValidators(sourceV);
    this.standard.controls.source.updateValueAndValidity({ emitEvent: false });

    // tags has no static validators; only required if the override sets it.
    const tagsRow = map['tags'];
    const tagsV: ValidatorFn[] = [];
    if (tagsRow?.is_required) tagsV.push(Validators.required);
    this.standard.controls.tags_csv.setValidators(tagsV);
    this.standard.controls.tags_csv.updateValueAndValidity({
      emitEvent: false,
    });
  }

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
    if (existing) {
      this.resetForm(existing);
    } else {
      // Create mode: default Owner to the signed-in user.
      const me = this.auth.currentUserId();
      if (me) {
        this.standard.controls.assigned_to_id.setValue(me, {
          emitEvent: false,
        });
      }
    }

    // Live duplicate check on phone / email. Debounced so a typing user
    // doesn't fire one HTTP call per keystroke; distinctUntilChanged
    // skips re-asking when the value matches the last submitted query.
    this.standard.controls.phone.valueChanges
      .pipe(
        debounceTime(400),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => this.runDuplicateCheck());
    this.standard.controls.email.valueChanges
      .pipe(
        debounceTime(400),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => this.runDuplicateCheck());
  }

  private runDuplicateCheck(): void {
    const phone = (this.standard.controls.phone.value ?? '').trim();
    const email = (this.standard.controls.email.value ?? '').trim();
    if (!phone && !email) {
      this.duplicates.set([]);
      return;
    }
    const excludeId = this._contact()?.id ?? null;
    this.api
      .checkDuplicate({
        phone: phone || null,
        email: email || null,
        excludeId,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => this.duplicates.set(resp.matches),
        // Failure here is non-fatal — duplicate-warning is best-effort.
        error: () => this.duplicates.set([]),
      });
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
      phone: nullableTrim(raw.phone),
      email: nullableTrim(raw.email),
      source: nullableTrim(raw.source),
      tags: this.parseTags(raw.tags_csv),
      assigned_to_id: nullableTrim(raw.assigned_to_id),
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
      assigned_to_id: contact.assigned_to_id ?? '',
    });
    this.customValue.set(contact.custom_data as FormValue);
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
