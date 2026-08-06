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
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { FurnitureAuthService } from '../auth/auth.service';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators, withRequiredIf } from '../shared/validators';
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
 *   - "Standard" — the canonical columns on the contacts row
 *     (full_name, phone, email, source, tags).
 *   - "Custom"   — the dynamic block driven by
 *     `GET /custom-fields/contact/render`, rendered through
 *     `<app-dynamic-form>`. Nothing about custom fields is hardcoded
 *     here (rule 4).
 */
@Component({
  selector: 'app-contact-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    DynamicFormComponent,
    LucideAngularModule,
    RouterLink,
    MobileSelectComponent,
  ],
  templateUrl: './contact-form-modal.component.html',
})
export class ContactFormModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'contact';

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  protected renderCustomFields$(): Observable<FieldDef[]> {
    return this.api.renderFields();
  }

  /** User list for the Owner dropdown. */
  protected readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** `crm-mobile-select` shape for the Owner picker (sentinel
   *  "Unassigned" + one entry per active org user). */
  protected readonly ownerSelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'Unassigned' },
    ...this.users().map((u) => ({ value: u.id, label: u.full_name })),
  ]);

  /** Live duplicate-match banner. Populated by debounced phone/email
   * watchers; the user can still save through it (legitimate cases:
   * shared household phone). */
  protected readonly duplicates = signal<ContactDuplicateMatch[]>([]);

  /** When set, the modal opens in edit mode. Null → create mode. */
  @Input() set contact(value: Contact | null) {
    this._contact.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Output() readonly save = new EventEmitter<{
    create?: ContactCreate;
    update?: ContactUpdate;
  }>();

  protected readonly _contact = signal<Contact | null>(null);

  readonly isEdit = computed(() => this._contact() !== null);

  readonly standard = this.fb.group({
    full_name: [
      '',
      [commonValidators.required, commonValidators.name, commonValidators.maxLength(255)],
    ],
    phone: ['', [commonValidators.phone(), commonValidators.maxLength(32)]],
    email: ['', [commonValidators.email, commonValidators.maxLength(254)]],
    source: ['', [commonValidators.maxLength(64)]],
    tags_csv: ['', [commonValidators.maxLength(1000)]],
    assigned_to_id: [''],
  });

  /** Override-driven validators on the standard FormGroup.
   *
   * The static "shape" validators (`commonValidators.email`, `commonValidators.maxLength`)
   * are always present — they're not overridable. `withRequiredIf` layers
   * `Validators.required` on top per the org's override choice. `full_name`
   * stays required always (registry locks it).
   */
  protected applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    // full_name — always required + name shape + max 255 (backend NOT NULL, backend max 255).
    this.standard.controls.full_name.setValidators([
      commonValidators.required,
      commonValidators.name,
      commonValidators.maxLength(255),
    ]);
    this.standard.controls.full_name.updateValueAndValidity({
      emitEvent: false,
    });

    this.standard.controls.phone.setValidators(
      withRequiredIf([commonValidators.phone(), commonValidators.maxLength(32)], map['phone']),
    );
    this.standard.controls.phone.updateValueAndValidity({ emitEvent: false });

    this.standard.controls.email.setValidators(
      withRequiredIf([commonValidators.email, commonValidators.maxLength(254)], map['email']),
    );
    this.standard.controls.email.updateValueAndValidity({ emitEvent: false });

    this.standard.controls.source.setValidators(
      withRequiredIf([commonValidators.maxLength(64)], map['source']),
    );
    this.standard.controls.source.updateValueAndValidity({ emitEvent: false });

    this.standard.controls.tags_csv.setValidators(
      withRequiredIf([commonValidators.maxLength(1000)], map['tags']),
    );
    this.standard.controls.tags_csv.updateValueAndValidity({
      emitEvent: false,
    });
  }

  override ngOnInit(): void {
    super.ngOnInit();

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
      .pipe(debounceTime(400), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.runDuplicateCheck());
    this.standard.controls.email.valueChanges
      .pipe(debounceTime(400), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
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
