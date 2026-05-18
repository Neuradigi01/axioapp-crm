import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import {
  ContactListItem,
  ContactsApiService,
} from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
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
  private readonly destroyRef = inject(DestroyRef);

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
