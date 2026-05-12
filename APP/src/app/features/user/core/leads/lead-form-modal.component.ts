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
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
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
import { Lead, LeadCreate, LeadUpdate, LeadsApiService } from './leads-api.service';

/**
 * Modal that creates or edits a `Lead`. Splits the form into:
 *
 *   - Contact picker — debounced search through the contacts API.
 *     Selected contact becomes the lead's `contact_id`. "Create new
 *     contact" intentionally redirects users to the Contacts page
 *     instead of inlining a second dynamic form (which would have to
 *     re-implement the entire required-custom-fields flow).
 *   - Standard fields — pipeline_stage (from the pipeline engine),
 *     budget, expected_close_date.
 *   - Custom fields — `<app-dynamic-form>` fed by the lead-scoped
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
  private readonly destroyRef = inject(DestroyRef);

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
            this.extractError(err) ?? 'Could not load custom field definitions.',
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
      budget: this.nullableTrim(raw.budget),
      expected_close_date: this.nullableTrim(raw.expected_close_date),
      custom_data: this.customValue() as Record<string, unknown>,
    };

    if (this.isEdit()) {
      // PATCH cannot change `pipeline_stage` (use move-stage endpoint).
      const update: LeadUpdate = {
        budget: payload.budget,
        expected_close_date: payload.expected_close_date,
        custom_data: payload.custom_data,
      };
      if (contact && contact.id !== this._lead()!.contact_id) {
        update.contact_id = contact.id;
      }
      this.save.emit({ update });
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
            created_at: c.created_at,
          }),
        error: () => {
          /* leave selectedContact null — the user can re-pick */
        },
      });
  }

  private nullableTrim(v: string | null | undefined): string | null {
    if (v === null || v === undefined) return null;
    const trimmed = v.trim();
    return trimmed.length === 0 ? null : trimmed;
  }

  private extractError(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
