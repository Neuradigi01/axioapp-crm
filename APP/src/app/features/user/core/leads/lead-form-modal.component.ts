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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import {
  ContactListItem,
  ContactsApiService,
} from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import {
  Pipeline,
  PipelinesApiService,
} from '../pipelines/pipelines-api.service';
import { StandardFieldsApiService } from '../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';
import { extractApiError } from '@core/services/api-error.util';
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
export class LeadFormModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly pipelinesApi = inject(PipelinesApiService);
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);

  // Standard fields registered for the `lead` entity. Render once on
  // open and again whenever the signal bus fires (Settings save / reset).
  // Keys are field_key — e.g. `stdFields()['budget']`.
  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>(
    {},
  );

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

  @Input() set lead(value: Lead | null) {
    this._lead.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Input() set submitError(value: string | null) {
    this._submitError.set(value);
  }

  @Output() readonly save = new EventEmitter<{
    create?: LeadCreate;
    update?: LeadUpdate;
    moveStageTo?: string;
  }>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _lead = signal<Lead | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _submitError = signal<string | null>(null);

  protected readonly fields = signal<FieldDef[]>([]);
  protected readonly fieldsLoading = signal(true);
  protected readonly fieldsError = signal<string | null>(null);

  protected readonly pipeline = signal<Pipeline | null>(null);

  protected readonly customValue = signal<FormValue>({});
  protected readonly customValid = signal(true);

  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactQuery = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchOpen = signal(false);

  private readonly contactQuery$ = new Subject<string>();

  readonly isEdit = computed(() => this._lead() !== null);
  readonly submitting$ = this._submitting.asReadonly();
  readonly submitError$ = this._submitError.asReadonly();

  readonly standard = this.fb.group({
    pipeline_stage: this.fb.control<string>('', { nonNullable: true }),
    budget: this.fb.control<string>('', { nonNullable: true }),
    expected_close_date: this.fb.control<string>('', { nonNullable: true }),
  });

  constructor() {
    // Refetch the override-merged defs whenever the Settings page bumps
    // the signal bus (a save or reset). On first mount the effect runs
    // once and kicks off the initial fetch, so `ngOnInit` doesn't need
    // to call render() again.
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  private refreshStdFields(): void {
    this.stdApi.render('lead').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        // Render is best-effort — the modal still works with the
        // hardcoded fallbacks below. Logging would be noisy; the auth
        // case (401) is already redirected by the interceptor.
      },
    });
  }

  /** Apply the override-driven validators to the standard FormGroup.
   *
   * Pipeline-stage stays required at all times (registry locks `required`).
   * Budget + expected_close_date pick up `Validators.required` if the
   * org marked them required. Budget additionally picks up min/max from
   * the override row when present.
   */
  private applyStandardValidators(
    map: Record<string, StandardFieldRendered>,
  ): void {
    const pipelineRow = map['pipeline_stage'];
    const budgetRow = map['budget'];
    const closeRow = map['expected_close_date'];

    // pipeline_stage — always required.
    this.standard.controls.pipeline_stage.setValidators([Validators.required]);
    this.standard.controls.pipeline_stage.updateValueAndValidity({
      emitEvent: false,
    });

    // budget — required if override says so; min/max if numeric bounds set.
    const budgetValidators: ValidatorFn[] = [];
    if (budgetRow?.is_required) budgetValidators.push(Validators.required);
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
    if (closeRow?.is_required) closeValidators.push(Validators.required);
    this.standard.controls.expected_close_date.setValidators(closeValidators);
    this.standard.controls.expected_close_date.updateValueAndValidity({
      emitEvent: false,
    });
  }

  ngOnInit(): void {
    // 1) lead custom field defs
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

    // 2) pipeline stages (drives the stage dropdown)
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

    // 3) contact search stream
    this.contactQuery$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) =>
          this.contactsApi.list({ q: q || undefined, size: 8 }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => this.contactResults.set(resp.items),
        error: () => this.contactResults.set([]),
      });

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
