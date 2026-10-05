import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
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
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { FormToastHelper } from '../shared/forms/form-toast.helper';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
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
  imports: [
    ReactiveFormsModule,
    DynamicFormComponent,
    MobileDateTimeComponent,
    MobileSelectComponent,
  ],
  templateUrl: './register-walkin-modal.component.html',
})
export class RegisterWalkinModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'walk_in';

  /** Canonical source options — mirror of the Contacts list Source
   *  column filter so a walk-in-picked source shows up under that
   *  filter without renaming. Bulk-import is omitted (never a walk-in
   *  origin). Referral / Phone added because reception commonly logs
   *  those alongside the raw walk-in. */
  protected readonly sourceOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'walk_in', label: 'Walk-in' },
    { value: 'referral', label: 'Referral' },
    { value: 'phone', label: 'Phone' },
    { value: 'widget', label: 'Forms' },
    { value: 'google_ads', label: 'Google Ads' },
    { value: 'meta_ads', label: 'Meta Ads' },
    { value: 'whatsapp_flow', label: 'WhatsApp' },
    { value: 'manual', label: 'Manual' },
  ];

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(WalkInsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly formToast = inject(FormToastHelper);
  private readonly confirmDialog = inject(ConfirmDialogService);
  /** True while the discard-changes confirm is up, so Esc doesn't stack. */
  private confirming = false;

  @Output() readonly registered = new EventEmitter<QuickRegisterResponse>();

  protected readonly matchedContact = signal<ContactListItem | null>(null);

  /** Browser-side bounds for the two date inputs, captured once at
   *  construction. The modal is short-lived so a "now" that's a few
   *  minutes stale is fine — the validators are authoritative.
   *
   *  Queue arrival (`<input type="datetime-local">`): [4h ago, now]
   *  in the `YYYY-MM-DDTHH:mm` shape the input expects.
   *
   *  Expected return (`<input type="date">`): [tomorrow, +365 days]
   *  in `YYYY-MM-DD`. */
  protected readonly waitStartedMin: string;
  protected readonly waitStartedMax: string;
  protected readonly expectedReturnMin: string;
  protected readonly expectedReturnMax: string;

  constructor() {
    super();
    const now = new Date();
    const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000);
    this.waitStartedMin = this.toLocalDateTimeInput(fourHoursAgo);
    this.waitStartedMax = this.toLocalDateTimeInput(now);
    // Return date lower bound is today (not tomorrow) — a customer
    // saying "I'll be back later today" is a legitimate reception
    // note. Backend `dateNotPast` on the control mirrors this. Upper
    // bound stays one year out (anything further is a typo).
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yearOut = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 365);
    this.expectedReturnMin = this.toLocalDateInput(today);
    this.expectedReturnMax = this.toLocalDateInput(yearOut);
  }

  private toLocalDateTimeInput(d: Date): string {
    const pad = (n: number): string => String(n).padStart(2, '0');
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }

  private toLocalDateInput(d: Date): string {
    const pad = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  protected readonly form = this.fb.group({
    // Prefill `+` so the country-code affordance is visible from open;
    // `onSubmit` treats a lone `+` as empty (which the required
    // validator catches). The phoneValidator enforces `+<code><digits>`.
    phone: this.fb.control('+', {
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
    // Reception-queue standard: within the last 4 hours, never future
    // (a wait that "started" yesterday is a data-entry mistake).
    wait_started_at: this.fb.control('', {
      nonNullable: true,
      validators: [
        commonValidators.isoDateTime,
        commonValidators.dateNotFuture,
        commonValidators.dateWithinPastHours(4),
      ],
    }),
    // W11 — "customer will return by" YYYY-MM-DD. Retention analytics.
    // Today is allowed (customer saying "I'll be back later today");
    // past is refused. Cap at one year out (anything further is a
    // typo).
    expected_return_date: this.fb.control('', {
      nonNullable: true,
      validators: [
        commonValidators.isoDate,
        commonValidators.dateNotPast,
        commonValidators.dateWithinFutureDays(365),
      ],
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
      // `nonNullable: true` on the control guarantees `value` is a
      // string today, but a future refactor or a stray `reset(null)`
      // would emit null and break `.trim()` inside the duplicate-
      // check pipe. `?? ''` guards defensively so a bad emit reads
      // as "no phone typed yet" rather than crashing the pipeline.
      .subscribe((value) => this.phoneInput$.next(value ?? ''));
  }

  /** Re-seed the `+` prefix on focus if it was cleared. */
  protected ensurePhonePrefix(): void {
    const value = this.form.controls.phone.value ?? '';
    if (!value.startsWith('+')) {
      this.form.controls.phone.setValue('+' + value.replace(/^\+*/, ''));
    }
  }

  /** Block Backspace / Delete when it would erase the leading `+`. */
  protected onPhoneKeydown(event: KeyboardEvent): void {
    const input = event.target as HTMLInputElement;
    const start = input.selectionStart ?? 0;
    const end = input.selectionEnd ?? 0;
    if (event.key === 'Backspace' && start <= 1 && end <= 1) {
      event.preventDefault();
    } else if (event.key === 'Delete' && start === 0 && end === 0) {
      event.preventDefault();
    }
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

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.confirming) void this.onCancel();
  }

  /** Cancel button / Esc. Asks before throwing away what was typed. */
  protected async onCancel(): Promise<void> {
    if (this._submitting()) return;
    if (this.form.dirty) {
      this.confirming = true;
      try {
        const ok = await this.confirmDialog.ask({
          title: 'Discard this walk-in?',
          body: 'The details you entered will be lost.',
          confirmLabel: 'Discard',
          danger: true,
        });
        if (!ok) return;
      } finally {
        this.confirming = false;
      }
    }
    this.cancel.emit();
  }

  protected onSubmit(): void {
    // A lone `+` (from the country-code prefill) counts as "no phone
    // entered" — clear it so `Validators.required` fires instead of
    // sending `+` to the backend.
    if ((this.form.controls.phone.value ?? '').trim() === '+') {
      this.form.controls.phone.setValue('');
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.formToast.requiredFieldsMissing();
      return;
    }
    if (!this.customValid()) {
      this._submitError.set('Please fix the highlighted custom fields.');
      this.formToast.requiredFieldsMissing();
      return;
    }
    this._submitError.set(null);
    this._submitting.set(true);

    const raw = this.form.getRawValue();
    // W8/W9/W11 — coerce optional strings to their typed shape or null
    // before hitting the backend (which is Pydantic-strict on int / iso
    // datetime / iso date).
    //
    // `party_size` binds to <input type="number">, which Angular's
    // NumberValueAccessor coerces to `number | null` regardless of the
    // control's declared string type. Treat all three runtime shapes
    // ('' when untouched, null when cleared, number when filled)
    // uniformly instead of calling .trim() on a non-string.
    const partySizeRaw = raw.party_size as unknown;
    const partySizeNum =
      typeof partySizeRaw === 'number' && Number.isFinite(partySizeRaw) ? partySizeRaw : null;
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
        party_size: partySizeNum,
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
