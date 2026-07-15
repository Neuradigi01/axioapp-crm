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
import { RouterLink } from '@angular/router';
import { Observable, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { Pipeline, PipelinesApiService } from '../pipelines/pipelines-api.service';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators } from '../shared/validators';
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';
import { nullableTrim } from '@core/services/form.util';

/**
 * Modal that creates or edits a `Lead`. Splits the form into:
 *
 *   - Contact picker â€” debounced search through the contacts API.
 *     Selected contact becomes the lead's `contact_id`. "Create new
 *     contact" intentionally redirects users to the Contacts page
 *     instead of inlining a second dynamic form (which would have to
 *     re-implement the entire required-custom-fields flow).
 *   - Standard fields â€” pipeline_stage (from the pipeline engine),
 *     budget, expected_close_date.
 *   - Custom fields â€” `<app-dynamic-form>` fed by the lead-scoped
 *     `/custom-fields/lead/render` endpoint.
 */
@Component({
  selector: 'app-lead-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, DynamicFormComponent],
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

  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);

  private readonly contactQuery$ = new Subject<string>();

  readonly isEdit = computed(() => this._lead() !== null);

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

    // pipeline_stage — always required.
    this.standard.controls.pipeline_stage.setValidators([commonValidators.required]);
    this.standard.controls.pipeline_stage.updateValueAndValidity({
      emitEvent: false,
    });

    // budget — required if override says so; min/max if numeric bounds set.
    const budgetValidators: ValidatorFn[] = [];
    if (budgetRow?.is_required) budgetValidators.push(commonValidators.required);
    if (budgetRow?.min_value !== null && budgetRow?.min_value !== undefined) {
      budgetValidators.push(Validators.min(budgetRow.min_value));
    }
    if (budgetRow?.max_value !== null && budgetRow?.max_value !== undefined) {
      budgetValidators.push(Validators.max(budgetRow.max_value));
    }
    this.standard.controls.budget.setValidators(budgetValidators);
    this.standard.controls.budget.updateValueAndValidity({ emitEvent: false });

    // expected_close_date — required if override says so.
    const closeValidators: ValidatorFn[] = [];
    if (closeRow?.is_required) closeValidators.push(commonValidators.required);
    this.standard.controls.expected_close_date.setValidators(closeValidators);
    this.standard.controls.expected_close_date.updateValueAndValidity({
      emitEvent: false,
    });
  }

  override ngOnInit(): void {
    super.ngOnInit();

    // pipeline stages (drives the stage dropdown)
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

    // contact search stream
    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => this.contactsApi.list({ q: q || undefined, size: 8 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => this.contactResults.set(resp.items),
        error: () => this.contactResults.set([]),
      });

    // Preload the first page so the dropdown opens instantly on focus.
    this.contactQuery$.next('');

    // If edit mode, fetch the contact so we can show its name in the chip.
    const existing = this._lead();
    if (existing) this.preloadEditContact(existing.contact_id);
  }

  protected onContactQueryInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.contactQuery.set(value);
    this.contactSearchOpen.set(true);
    this.contactQuery$.next(value);
  }

  protected onContactFocus(): void {
    this.contactSearchOpen.set(true);
    if (this.contactResults().length === 0) {
      this.contactQuery$.next(this.contactQuery());
    }
  }

  protected onContactBlur(): void {
    setTimeout(() => this.contactSearchOpen.set(false), 150);
  }

  protected selectContact(c: ContactListItem): void {
    this.selectedContact.set(c);
    this.contactSearchOpen.set(false);
    this.contactQuery.set('');
    this.contactResults.set([]);
    this._submitError.set(null);
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.contactQuery.set('');
    this.contactResults.set([]);
    this.contactSearchOpen.set(true);
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
    const contact = this.selectedContact();
    if (!contact && !this.isEdit()) {
      this._submitError.set('Please pick a contact.');
      return;
    }
    this._submitError.set(null);

    const raw = this.standard.getRawValue();
    const payload: LeadCreate = {
      contact_id: contact ? contact.id : this._lead()!.contact_id,
      pipeline_stage: raw.pipeline_stage || null,
      budget: nullableTrim(raw.budget),
      expected_close_date: nullableTrim(raw.expected_close_date),
      custom_data: this.customValue() as Record<string, unknown>,
    };

    if (this.isEdit()) {
      const existing = this._lead()!;
      const update: LeadUpdate = {
        budget: payload.budget,
        expected_close_date: payload.expected_close_date,
        custom_data: payload.custom_data,
      };
      if (contact && contact.id !== existing.contact_id) {
        update.contact_id = contact.id;
      }
      const moveStageTo =
        raw.pipeline_stage && raw.pipeline_stage !== existing.pipeline_stage
          ? raw.pipeline_stage
          : undefined;
      this.save.emit({ update, moveStageTo });
    } else {
      this.save.emit({ create: payload });
    }
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
          /* leave selectedContact null â€” the user can re-pick */
        },
      });
  }
}
