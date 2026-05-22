import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  OnInit,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import {
  ContactListItem,
  ContactsApiService,
} from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { StandardFieldsApiService } from '../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';
import {
  QuickRegisterResponse,
  WalkInsApiService,
} from './walk-ins-api.service';

/**
 * Reception-desk one-shot modal. Phone-first: when the operator types
 * a phone number, we debounce + lookup an existing contact; if one
 * exists with that exact phone we show a banner ("Existing customer:
 * Asha Reddy"). The backend dedups regardless, so this is a UX hint
 * only â€” the operator can still type any name and submit.
 *
 * The Custom section renders `<app-dynamic-form>` against
 * `entity_type='walk_in'`. Contact custom fields are NOT enforced at
 * this surface â€” the backend's `quick-register` bypasses them on
 * contact creation (operator fills the rest later via Contacts page).
 */
@Component({
  selector: 'app-register-walkin-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DynamicFormComponent],
  templateUrl: './register-walkin-modal.component.html',
})
export class RegisterWalkinModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(WalkInsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>(
    {},
  );

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

  @Output() readonly registered = new EventEmitter<QuickRegisterResponse>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly matchedContact = signal<ContactListItem | null>(null);

  protected readonly fields = signal<FieldDef[]>([]);
  protected readonly fieldsLoading = signal(true);
  protected readonly fieldsError = signal<string | null>(null);
  protected readonly customValue = signal<FormValue>({});
  protected readonly customValid = signal(true);

  protected readonly form = this.fb.group({
    phone: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(32)],
    }),
    full_name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    email: this.fb.control('', { nonNullable: true }),
    source: this.fb.control('walk_in', { nonNullable: true }),
    requirement: this.fb.control('', { nonNullable: true }),
    budget: this.fb.control('', { nonNullable: true }),
  });

  protected readonly hasMatch = computed(() => this.matchedContact() !== null);

  private readonly phoneInput$ = new Subject<string>();

  constructor() {
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  private refreshStdFields(): void {
    this.stdApi.render('walk_in').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        /* fallbacks keep the form usable */
      },
    });
  }

  /** Layer override-driven validators on top of static shape validators.
   *
   * `phone` + `full_name` stay always-required (backend NOT NULL). The
   * other four (email, source, requirement, budget) accept `required`
   * overrides; `budget` additionally accepts `min`/`max`.
   */
  private applyStandardValidators(
    map: Record<string, StandardFieldRendered>,
  ): void {
    this.form.controls.phone.setValidators([
      Validators.required,
      Validators.maxLength(32),
    ]);
    this.form.controls.phone.updateValueAndValidity({ emitEvent: false });

    this.form.controls.full_name.setValidators([
      Validators.required,
      Validators.maxLength(255),
    ]);
    this.form.controls.full_name.updateValueAndValidity({ emitEvent: false });

    const setReq = (
      ctrl: keyof typeof this.form.controls,
      base: ValidatorFn[],
      row: StandardFieldRendered | undefined,
    ): void => {
      const v = [...base];
      if (row?.is_required) v.push(Validators.required);
      this.form.controls[ctrl].setValidators(v);
      this.form.controls[ctrl].updateValueAndValidity({ emitEvent: false });
    };

    setReq('email', [], map['email']);
    setReq('source', [], map['source']);
    setReq('requirement', [], map['requirement']);

    const budgetRow = map['budget'];
    const budgetV: ValidatorFn[] = [];
    if (budgetRow?.is_required) budgetV.push(Validators.required);
    if (budgetRow?.min_value != null) budgetV.push(Validators.min(budgetRow.min_value));
    if (budgetRow?.max_value != null) budgetV.push(Validators.max(budgetRow.max_value));
    this.form.controls.budget.setValidators(budgetV);
    this.form.controls.budget.updateValueAndValidity({ emitEvent: false });
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

    // Phone-match lookup. Debounced so we don't flood as the user types.
    this.phoneInput$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((phone) => {
          const trimmed = phone.trim();
          if (trimmed.length < 4) {
            this.matchedContact.set(null);
            return [];
          }
          return this.contactsApi.list({ q: trimmed, size: 5 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          if (!resp) return;
          // Exact-phone match wins; otherwise no match shown.
          const typed = this.form.controls.phone.value.trim();
          const exact = resp.items.find((c) => c.phone === typed);
          this.matchedContact.set(exact ?? null);
        },
        error: () => this.matchedContact.set(null),
      });

    this.form.controls.phone.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.phoneInput$.next(value));
  }

  protected onCustomValueChange(v: FormValue): void {
    this.customValue.set(v);
  }

  protected onCustomValidityChange(valid: boolean): void {
    this.customValid.set(valid);
  }

  protected useMatchedContact(): void {
    const m = this.matchedContact();
    if (!m) return;
    this.form.patchValue({
      full_name: m.full_name,
      email: m.email ?? '',
      source: m.source ?? 'walk_in',
    });
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    if (!this.customValid()) {
      this.submitError.set('Please fix the highlighted custom fields.');
      return;
    }
    this.submitError.set(null);
    this.submitting.set(true);

    const raw = this.form.getRawValue();
    this.api
      .quickRegister({
        phone: raw.phone.trim(),
        full_name: raw.full_name.trim(),
        email: nullableTrim(raw.email),
        source: nullableTrim(raw.source),
        requirement: nullableTrim(raw.requirement),
        budget: nullableTrim(raw.budget),
        custom_data: this.customValue() as Record<string, unknown>,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.submitting.set(false);
          this.registered.emit(result);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(
            extractApiError(err) ?? 'Could not register walk-in.',
          );
        },
      });
  }


}
