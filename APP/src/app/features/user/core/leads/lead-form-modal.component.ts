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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { Pipeline, PipelinesApiService } from '../pipelines/pipelines-api.service';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators } from '../shared/validators';
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';
import { nullableTrim } from '@core/services/form.util';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Modal that creates or edits a `Lead`.
 *
 * Create mode collects the primary contact's name / phone / email
 * inline (there is no separate contact picker) and, on submit, either
 * re-uses an existing contact matched by phone/email or creates a new
 * one before writing the lead. Standard + custom fields work the same
 * way as the other entity modals.
 *
 * Edit mode shows the linked contact read-only. The modal only edits
 * lead columns; changing which contact a lead points at is deliberately
 * out of scope for this UI.
 */
@Component({
  selector: 'app-lead-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    DynamicFormComponent,
    MobileSelectComponent,
    MobileDateTimeComponent,
  ],
  templateUrl: './lead-form-modal.component.html',
})
export class LeadFormModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'lead';

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly pipelinesApi = inject(PipelinesApiService);

  @Input() set lead(value: Lead | null) {
    this._lead.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Output() readonly save = new EventEmitter<{
    create?: LeadCreate;
    update?: LeadUpdate;
    moveStageTo?: string;
  }>();

  protected readonly _lead = signal<Lead | null>(null);

  protected readonly pipeline = signal<Pipeline | null>(null);

  /** `crm-mobile-select` shape for the pipeline-stage picker. Empty
   *  while `pipeline()` is still loading. */
  protected readonly stageSelectOptions = computed<{ value: string; label: string }[]>(
    () => this.pipeline()?.stages.map((s) => ({ value: s.key, label: s.name })) ?? [],
  );

  /** Populated in edit mode so the linked contact's name / phone / email
   * can be surfaced read-only. Never used in create mode. */
  protected readonly selectedContact = signal<ContactListItem | null>(null);

  readonly isEdit = computed(() => this._lead() !== null);

  /** Contact basics captured inline in create mode. On submit these are
   * either matched against an existing contact (via the duplicate-check
   * endpoint) or written as a new contact — the resulting id becomes
   * the lead's `contact_id`. */
  readonly contactBasics = this.fb.group({
    full_name: this.fb.control<string>('', { nonNullable: true }),
    // Prefill `+` so the country-code affordance is visible from open;
    // `resolveContactThenEmit` treats a lone `+` as "no phone entered".
    phone: this.fb.control<string>('+', { nonNullable: true }),
    email: this.fb.control<string>('', { nonNullable: true }),
  });

  /** Re-seed the `+` prefix on focus if it was cleared. */
  protected ensurePhonePrefix(): void {
    const value = this.contactBasics.controls.phone.value ?? '';
    if (!value.startsWith('+')) {
      this.contactBasics.controls.phone.setValue('+' + value.replace(/^\+*/, ''));
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

  readonly standard = this.fb.group({
    pipeline_stage: this.fb.control<string>('', { nonNullable: true }),
    budget: this.fb.control<string>('', { nonNullable: true }),
    expected_close_date: this.fb.control<string>('', { nonNullable: true }),
  });

  protected renderCustomFields$(): Observable<FieldDef[]> {
    return this.api.renderFields();
  }

  /** Apply the override-driven validators to the standard FormGroup.
   *
   * Pipeline-stage stays required at all times (registry locks `required`).
   * Budget + expected_close_date pick up `commonValidators.required` if the
   * org marked them required. Budget additionally picks up min/max from
   * the override row when present.
   */
  protected applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    const budgetRow = map['budget'];
    const closeRow = map['expected_close_date'];

    this.standard.controls.pipeline_stage.setValidators([commonValidators.required]);
    this.standard.controls.pipeline_stage.updateValueAndValidity({
      emitEvent: false,
    });

    // Floor + ceiling always apply; override min/max tighten further if set.
    const budgetValidators: ValidatorFn[] = [commonValidators.numericInRange(0, 1_000_000_000)];
    if (budgetRow?.is_required) budgetValidators.push(commonValidators.required);
    if (budgetRow?.min_value !== null && budgetRow?.min_value !== undefined) {
      budgetValidators.push(Validators.min(budgetRow.min_value));
    }
    if (budgetRow?.max_value !== null && budgetRow?.max_value !== undefined) {
      budgetValidators.push(Validators.max(budgetRow.max_value));
    }
    this.standard.controls.budget.setValidators(budgetValidators);
    this.standard.controls.budget.updateValueAndValidity({ emitEvent: false });

    // Expected close date is a forward-looking projection — if the lead
    // is actually closing today the rep clicks Won, they don't set an
    // expectation. Enforce "tomorrow onward" via `dateFuture` (stricter
    // than `dateNotPast` which allows today).
    const closeValidators: ValidatorFn[] = [commonValidators.isoDate, commonValidators.dateFuture];
    if (closeRow?.is_required) closeValidators.push(commonValidators.required);
    this.standard.controls.expected_close_date.setValidators(closeValidators);
    this.standard.controls.expected_close_date.updateValueAndValidity({
      emitEvent: false,
    });
  }

  override ngOnInit(): void {
    super.ngOnInit();

    if (!this.isEdit()) {
      this.contactBasics.controls.full_name.setValidators([
        commonValidators.required,
        commonValidators.name,
        commonValidators.maxLength(255),
      ]);
      this.contactBasics.controls.phone.setValidators([
        commonValidators.phone(),
        commonValidators.maxLength(32),
      ]);
      this.contactBasics.controls.email.setValidators([
        commonValidators.email,
        commonValidators.maxLength(254),
      ]);
      this.contactBasics.controls.full_name.updateValueAndValidity({ emitEvent: false });
      this.contactBasics.controls.phone.updateValueAndValidity({ emitEvent: false });
      this.contactBasics.controls.email.updateValueAndValidity({ emitEvent: false });
    }

    this.pipelinesApi
      .getByKey('leads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.pipeline.set(p);
          if (!this.standard.controls.pipeline_stage.value && !this.isEdit()) {
            const first = [...p.stages].sort((a, b) => a.display_order - b.display_order)[0];
            if (first) this.standard.controls.pipeline_stage.setValue(first.key);
          }
        },
        error: () => this.pipeline.set(null),
      });

    const existing = this._lead();
    if (existing) this.preloadEditContact(existing.contact_id);
  }

  protected onCustomValueChange(v: FormValue): void {
    this.customValue.set(v);
  }

  protected onCustomValidityChange(v: boolean): void {
    this.customValid.set(v);
  }

  protected onSubmit(): void {
    if (this.standard.invalid) {
      this.standard.markAllAsTouched();
      return;
    }
    if (!this.customValid()) {
      this._submitError.set('Please fix the highlighted custom fields.');
      return;
    }

    if (this.isEdit()) {
      this.emitUpdate();
      return;
    }

    if (this.contactBasics.invalid) {
      this.contactBasics.markAllAsTouched();
      this._submitError.set('Please fill the contact details.');
      return;
    }
    this._submitError.set(null);
    this.resolveContactThenEmit();
  }

  private emitUpdate(): void {
    const raw = this.standard.getRawValue();
    const existing = this._lead()!;
    const update: LeadUpdate = {
      budget: nullableTrim(raw.budget),
      expected_close_date: nullableTrim(raw.expected_close_date),
      custom_data: this.customValue() as Record<string, unknown>,
    };
    const moveStageTo =
      raw.pipeline_stage && raw.pipeline_stage !== existing.pipeline_stage
        ? raw.pipeline_stage
        : undefined;
    this.save.emit({ update, moveStageTo });
  }

  /** Find-or-create the contact from the inline basics, then emit the
   * lead create. Uses `checkDuplicate` to match on phone/email before
   * writing a new row so re-entering an existing customer's details
   * links to the same contact rather than piling up dupes.
   *
   * When a match's phone or email is empty and the operator typed a
   * value, PATCH the existing contact so the data the operator entered
   * lands rather than being silently discarded (option (a) — enrich
   * rather than overwrite; existing non-empty values are never
   * clobbered). */
  private resolveContactThenEmit(): void {
    const basics = this.contactBasics.getRawValue();
    const full_name = basics.full_name.trim();
    const phoneTrimmed = basics.phone.trim();
    // A lone `+` (from the country-code prefill) means no phone entered.
    const phone = phoneTrimmed === '' || phoneTrimmed === '+' ? null : phoneTrimmed;
    const email = basics.email.trim() || null;

    this._submitting.set(true);
    this.contactsApi
      .checkDuplicate({ phone, email })
      .pipe(
        switchMap((resp) => {
          const match = resp.matches[0];
          if (match) {
            const patch: Record<string, string> = {};
            if (!match.phone && phone) patch['phone'] = phone;
            if (!match.email && email) patch['email'] = email;
            if (Object.keys(patch).length === 0) return of(match.id);
            return this.contactsApi.update(match.id, patch).pipe(map((c) => c.id));
          }
          return this.contactsApi.createStub({ full_name, phone, email }).pipe(map((c) => c.id));
        }),
        catchError((err: HttpErrorResponse) => {
          this._submitting.set(false);
          this._submitError.set(extractApiError(err) ?? 'Could not create contact.');
          return of(null);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((contactId) => {
        this._submitting.set(false);
        if (!contactId) return;
        const raw = this.standard.getRawValue();
        const payload: LeadCreate = {
          contact_id: contactId,
          pipeline_stage: raw.pipeline_stage || null,
          budget: nullableTrim(raw.budget),
          expected_close_date: nullableTrim(raw.expected_close_date),
          custom_data: this.customValue() as Record<string, unknown>,
        };
        this.save.emit({ create: payload });
      });
  }

  private resetForm(lead: Lead): void {
    this.standard.reset({
      pipeline_stage: lead.pipeline_stage,
      budget: lead.budget ?? '',
      expected_close_date: lead.expected_close_date ?? '',
    });
    this.customValue.set(lead.custom_data as FormValue);
  }

  private preloadEditContact(contactId: string): void {
    this.contactsApi
      .get(contactId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) =>
          this.selectedContact.set({
            id: c.id,
            full_name: c.full_name,
            phone: c.phone,
            email: c.email,
            source: c.source,
            tags: c.tags,
            assigned_to_id: c.assigned_to_id,
            last_activity_at: c.last_activity_at,
            created_at: c.created_at,
          }),
        error: () => {
          /* leave selectedContact null — the contact chip just won't render */
        },
      });
  }
}
