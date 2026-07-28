import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators } from '../shared/validators';
import { extractApiError } from '@core/services/api-error.util';
import { nullableTrim } from '@core/services/form.util';
import { QuickRegisterResponse, WalkInsApiService } from './walk-ins-api.service';

/**
 * Reception-desk one-shot modal. Phone-first: when the operator types
 * a phone number, we debounce + lookup an existing contact; if one
 * exists with that exact phone we show a banner ("Existing customer:
 * Asha Reddy"). The backend dedups regardless, so this is a UX hint
 * only — the operator can still type any name and submit.
 *
 * The Custom section renders `<app-dynamic-form>` against
 * `entity_type='walk_in'`. Contact custom fields are NOT enforced at
 * this surface — the backend's `quick-register` bypasses them on
 * contact creation (operator fills the rest later via Contacts page).
 */
@Component({
  selector: 'app-register-walkin-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DynamicFormComponent],
  templateUrl: './register-walkin-modal.component.html',
})
export class RegisterWalkinModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'walk_in';

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(WalkInsApiService);
  private readonly contactsApi = inject(ContactsApiService);

  @Output() readonly registered = new EventEmitter<QuickRegisterResponse>();

  protected readonly matchedContact = signal<ContactListItem | null>(null);

  protected readonly form = this.fb.group({
    phone: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, commonValidators.phone(), Validators.maxLength(32)],
    }),
    full_name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, commonValidators.name, Validators.maxLength(255)],
    }),
    email: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.email, commonValidators.maxLength(254)],
    }),
    source: this.fb.control('walk_in', { nonNullable: true }),
    requirement: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.maxLength(500)],
    }),
    budget: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.numericInRange(0, 1_000_000_000)],
    }),
    // W8 — party size (1–99). Empty = single visitor / not tracked.
    party_size: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.numericInRange(1, 99)],
    }),
    // W9 — queue arrival ISO. When present, the (time_in - wait_started_at)
    // delta populates the org's avg-wait metric. Empty = not tracked.
    wait_started_at: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.isoDateTime],
    }),
    // W11 — "customer will return by" YYYY-MM-DD. Retention analytics.
    // "Will return" is forward-looking — today doesn't make sense for
    // an expected-return promise, so `dateFuture` (tomorrow onward).
    expected_return_date: this.fb.control('', {
      nonNullable: true,
      validators: [commonValidators.isoDate, commonValidators.dateFuture],
    }),
  });

  protected readonly hasMatch = computed(() => this.matchedContact() !== null);

  private readonly phoneInput$ = new Subject<string>();

  protected renderCustomFields$(): Observable<FieldDef[]> {
    return this.api.renderFields();
  }

  /** Layer override-driven validators on top of static shape validators.
   *
   * `phone` + `full_name` stay always-required (backend NOT NULL). The
   * other four (email, source, requirement, budget) accept `required`
   * overrides; `budget` additionally accepts `min`/`max`.
   */
  protected applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    this.form.controls.phone.setValidators([
      Validators.required,
      commonValidators.phone(),
      Validators.maxLength(32),
    ]);
    this.form.controls.phone.updateValueAndValidity({ emitEvent: false });

    this.form.controls.full_name.setValidators([
      Validators.required,
      commonValidators.name,
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

    setReq('email', [commonValidators.email, commonValidators.maxLength(254)], map['email']);
    setReq('source', [], map['source']);
    setReq('requirement', [commonValidators.maxLength(500)], map['requirement']);

    const budgetRow = map['budget'];
    // Floor + ceiling always apply; override min/max tighten further if set.
    const budgetV: ValidatorFn[] = [commonValidators.numericInRange(0, 1_000_000_000)];
    if (budgetRow?.is_required) budgetV.push(Validators.required);
    if (budgetRow?.min_value != null) budgetV.push(Validators.min(budgetRow.min_value));
    if (budgetRow?.max_value != null) budgetV.push(Validators.max(budgetRow.max_value));
    this.form.controls.budget.setValidators(budgetV);
    this.form.controls.budget.updateValueAndValidity({ emitEvent: false });
  }

  override ngOnInit(): void {
    super.ngOnInit();

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
      this._submitError.set('Please fix the highlighted custom fields.');
      return;
    }
    this._submitError.set(null);
    this._submitting.set(true);

    const raw = this.form.getRawValue();
    // W8/W9/W11 — coerce optional strings to their typed shape or null
    // before hitting the backend (which is Pydantic-strict on int / iso
    // datetime / iso date).
    const partySize = raw.party_size.trim();
    const partySizeNum = partySize ? Number.parseInt(partySize, 10) : null;
    const waitStr = raw.wait_started_at.trim();
    const returnStr = raw.expected_return_date.trim();
    this.api
      .quickRegister({
        phone: raw.phone.trim(),
        full_name: raw.full_name.trim(),
        email: nullableTrim(raw.email),
        source: nullableTrim(raw.source),
        requirement: nullableTrim(raw.requirement),
        budget: nullableTrim(raw.budget),
        custom_data: this.customValue() as Record<string, unknown>,
        party_size: partySizeNum && Number.isFinite(partySizeNum) ? partySizeNum : null,
        wait_started_at: waitStr ? new Date(waitStr).toISOString() : null,
        expected_return_date: returnStr || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this._submitting.set(false);
          this.registered.emit(result);
        },
        error: (err: HttpErrorResponse) => {
          this._submitting.set(false);
          this._submitError.set(extractApiError(err) ?? 'Could not register walk-in.');
        },
      });
  }
}
