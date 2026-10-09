import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, OrgSummary } from '../../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { stripPhoneSeparators } from '../../../../../shared/validators/custom-validators';
import { FormToastHelper } from '../../shared/forms/form-toast.helper';
import { commonValidators } from '../../shared/validators';
import { OrgSettings, SettingsApiService } from '../settings-api.service';

/**
 * Store Profile tab — the meat of OrgSettings. Logo, store name,
 * GST, full address, phone, email, currency, tax_rate, timezone,
 * locale. Submits only the dirty keys via PATCH (strict-key on the
 * backend side too).
 */
import { ComplianceSettingsComponent } from '../general/compliance-settings.component';

interface ReminderPreset {
  label: string;
  minutes: number;
}

const REMINDER_PRESETS: readonly ReminderPreset[] = [
  { label: '15 min', minutes: 15 },
  { label: '30 min', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '3 hours', minutes: 180 },
  { label: '1 day', minutes: 1440 },
  { label: '2 days', minutes: 2880 },
  { label: '1 week', minutes: 10080 },
];

/** Store-profile form fields and the label each error message uses. */
const FIELD_LABELS = {
  store_name: 'Store name',
  logo_url: 'Logo URL',
  gst_number: 'GST number',
  phone: 'Phone',
  email: 'Email',
  address_line1: 'Address line 1',
  address_line2: 'Address line 2',
  city: 'City',
  state: 'State',
  postal_code: 'Postal code',
  country: 'Country',
  currency: 'Currency',
  tax_rate: 'Tax rate',
  timezone: 'Timezone',
  locale: 'Locale',
} as const;

type StoreField = keyof typeof FIELD_LABELS;

/** Trim text, send blanks as null, and canonicalise the coded fields
 *  (GSTIN / currency upper-case, phone without separators) so the
 *  stored value matches what the validators accepted. */
function normalizeField(name: StoreField, value: unknown): unknown {
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  if (trimmed === '') return null;
  if (name === 'gst_number' || name === 'currency') return trimmed.toUpperCase();
  if (name === 'phone') return stripPhoneSeparators(trimmed);
  return trimmed;
}

const REMINDER_MIN_MINUTES = 5;
const REMINDER_MAX_MINUTES = 43200;
const REMINDER_MAX_ENTRIES = 10;

@Component({
  selector: 'app-settings-store-profile-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, ComplianceSettingsComponent],
  templateUrl: './store-profile-tab.component.html',
})
export class StoreProfileTabComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(SettingsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);
  private readonly formToast = inject(FormToastHelper);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saveOk = signal(false);
  /** Read-only org identity surfaced above the editable form (DR.5 + 2.5.4). */
  protected readonly org = signal<OrgSummary | null>(null);
  /** Gate the Save button on `settings.write`. Read access alone keeps the
   * form viewable but unsubmittable — same UX shape as the Roles tab. */
  protected readonly canWrite = signal(false);

  // --- Appointment reminders (inlined section) ------------------------
  protected readonly reminderPresets = REMINDER_PRESETS;
  protected readonly reminderLoading = signal(true);
  protected readonly reminderSaving = signal(false);
  protected readonly reminderSaved = signal(false);
  protected readonly reminderError = signal<string | null>(null);
  protected readonly reminderCustomError = signal<string | null>(null);
  protected readonly reminderOffsets = signal<number[]>([1440, 60]);

  protected isReminderSelected(minutes: number): boolean {
    return this.reminderOffsets().includes(minutes);
  }

  protected toggleReminderPreset(minutes: number): void {
    const current = this.reminderOffsets();
    if (current.includes(minutes)) {
      this.reminderOffsets.set(current.filter((m) => m !== minutes));
    } else {
      if (current.length >= REMINDER_MAX_ENTRIES) {
        this.reminderError.set(`Only up to ${REMINDER_MAX_ENTRIES} reminders are allowed.`);
        return;
      }
      this.reminderOffsets.set([...current, minutes].sort((a, b) => b - a));
    }
    this.reminderSaved.set(false);
    this.reminderError.set(null);
  }

  protected addCustomReminder(input: HTMLInputElement): void {
    this.reminderCustomError.set(null);
    const raw = input.value?.trim() ?? '';
    if (raw === '') {
      this.reminderCustomError.set('Enter a number of minutes.');
      return;
    }
    const value = Math.trunc(Number(raw));
    if (!Number.isFinite(value)) {
      this.reminderCustomError.set('Enter a whole number.');
      return;
    }
    if (value < REMINDER_MIN_MINUTES) {
      this.reminderCustomError.set(`Minimum is ${REMINDER_MIN_MINUTES} minutes.`);
      return;
    }
    if (value > REMINDER_MAX_MINUTES) {
      this.reminderCustomError.set('Maximum is 30 days (43200 minutes).');
      return;
    }
    const current = this.reminderOffsets();
    if (current.includes(value)) {
      this.reminderCustomError.set('Already added.');
      return;
    }
    if (current.length >= REMINDER_MAX_ENTRIES) {
      this.reminderCustomError.set(`Only up to ${REMINDER_MAX_ENTRIES} reminders are allowed.`);
      return;
    }
    this.reminderOffsets.set([...current, value].sort((a, b) => b - a));
    input.value = '';
    this.reminderSaved.set(false);
  }

  protected removeReminder(minutes: number): void {
    this.reminderOffsets.set(this.reminderOffsets().filter((m) => m !== minutes));
    this.reminderSaved.set(false);
  }

  protected reminderLabel(minutes: number): string {
    if (minutes % 1440 === 0) {
      const days = minutes / 1440;
      return days === 1 ? '1 day before' : `${days} days before`;
    }
    if (minutes % 60 === 0) {
      const hours = minutes / 60;
      return hours === 1 ? '1 hour before' : `${hours} hours before`;
    }
    return `${minutes} min before`;
  }

  protected saveReminders(): void {
    this.reminderSaving.set(true);
    this.reminderSaved.set(false);
    this.reminderError.set(null);
    this.api
      .patch({ appointment_reminder_offsets_minutes: this.reminderOffsets() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.reminderOffsets.set(s.appointment_reminder_offsets_minutes ?? []);
          this.reminderSaving.set(false);
          this.reminderSaved.set(true);
          this.toast.success('Appointment reminders saved.');
        },
        error: (err: HttpErrorResponse) => {
          this.reminderSaving.set(false);
          const msg = extractApiError(err) ?? 'Could not save reminder settings.';
          this.reminderError.set(msg);
          this.toast.error('Could not save appointment reminders.', { subtitle: msg });
        },
      });
  }

  // Limits mirror `OrgSettingsPatch` in api/src/app/core/settings/schemas.py.
  protected readonly form = this.fb.group({
    store_name: this.fb.control<string | null>(null, [
      commonValidators.trimmedRequired,
      commonValidators.maxLength(255),
    ]),
    logo_url: this.fb.control<string | null>(null, [
      commonValidators.url,
      commonValidators.maxLength(512),
    ]),
    gst_number: this.fb.control<string | null>(null, [commonValidators.gstin]),
    address_line1: this.fb.control<string | null>(null, [commonValidators.maxLength(255)]),
    address_line2: this.fb.control<string | null>(null, [commonValidators.maxLength(255)]),
    city: this.fb.control<string | null>(null, [commonValidators.maxLength(128)]),
    state: this.fb.control<string | null>(null, [commonValidators.maxLength(128)]),
    postal_code: this.fb.control<string | null>(null, [commonValidators.postalCode]),
    country: this.fb.control<string | null>(null, [commonValidators.maxLength(64)]),
    phone: this.fb.control<string | null>(null, [
      commonValidators.phone(),
      commonValidators.maxLength(32),
    ]),
    email: this.fb.control<string | null>(null, [
      commonValidators.email,
      commonValidators.maxLength(255),
    ]),
    currency: this.fb.control<string>('INR', {
      nonNullable: true,
      validators: [commonValidators.trimmedRequired, commonValidators.currencyCode],
    }),
    tax_rate: this.fb.control<string>('18.00', {
      nonNullable: true,
      validators: [
        commonValidators.required,
        commonValidators.numericInRange(0, 100),
        commonValidators.maxDecimals(2),
      ],
    }),
    timezone: this.fb.control<string>('Asia/Kolkata', {
      nonNullable: true,
      validators: [commonValidators.trimmedRequired, commonValidators.timezone],
    }),
    locale: this.fb.control<string>('en-IN', {
      nonNullable: true,
      validators: [commonValidators.trimmedRequired, commonValidators.locale],
    }),
  });

  /** Error text under `name`'s input once the operator has touched it,
   *  or null while it is untouched / valid. */
  protected fieldError(name: StoreField): string | null {
    const ctrl = this.form.controls[name];
    if (!ctrl.touched || !ctrl.errors) return null;
    const errors = ctrl.errors;
    const label = FIELD_LABELS[name];
    if (errors['required']) return `${label} is required.`;
    if (errors['maxlength']) {
      return `${label} must be at most ${errors['maxlength'].requiredLength} characters.`;
    }
    if (errors['emailInvalid']) return 'Enter a valid email address, e.g. store@company.com.';
    if (errors['phoneInvalid']) return 'Include the country code, e.g. +919876543210.';
    if (errors['urlInvalid']) return 'Enter a full link starting with https://';
    if (errors['gstinInvalid']) {
      return 'Enter a valid GSTIN: 2-digit state code, 10-character PAN, then 3 characters, e.g. 29ABCDE1234F1Z5.';
    }
    if (errors['postalCodeInvalid']) return 'Use 3–10 letters or digits, e.g. 560001.';
    if (errors['currencyInvalid']) return 'Use a 3-letter currency code, e.g. INR or USD.';
    if (errors['invalidNumber'] || errors['outOfRange']) return 'Enter a rate from 0 to 100.';
    if (errors['tooManyDecimals']) return 'Use at most 2 decimal places.';
    if (errors['timezoneInvalid']) return 'Use a timezone like Asia/Kolkata or UTC.';
    if (errors['localeInvalid']) return 'Use a locale like en-IN or en-US.';
    return `${label} is invalid.`;
  }

  constructor() {
    this.reload();
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => {
          this.org.set(me.org);
          this.canWrite.set(me.permission_keys.includes('settings.write'));
        },
        error: () => {
          this.org.set(null);
          this.canWrite.set(false);
        },
      });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          const msg = extractApiError(err) ?? 'Could not load settings.';
          this.loadError.set(msg);
          this.toast.error('Could not load store profile.', { subtitle: msg });
        },
      });
  }

  protected save(): void {
    if (!this.canWrite()) return;
    this.saveError.set(null);
    this.saveOk.set(false);

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      const invalid = (Object.keys(FIELD_LABELS) as StoreField[]).filter(
        (name) => this.form.controls[name].invalid,
      );
      const missingRequired = invalid.some((name) => this.form.controls[name].errors?.['required']);
      const labels = invalid.map((name) => FIELD_LABELS[name]);
      if (missingRequired) {
        this.formToast.requiredFieldsMissing(`Check: ${labels.join(', ')}.`);
      } else {
        this.formToast.invalidFields(labels);
      }
      return;
    }

    // Only send dirty controls so we honor the strict-key PATCH on
    // the backend (and don't accidentally re-write defaults).
    const dirty: Record<string, unknown> = {};
    for (const [key, ctrl] of Object.entries(this.form.controls)) {
      if (ctrl.dirty) dirty[key] = normalizeField(key as StoreField, ctrl.value);
    }
    this.saving.set(true);
    if (Object.keys(dirty).length === 0) {
      this.saving.set(false);
      this.saveOk.set(true);
      this.toast.info('No changes to save.');
      return;
    }

    this.api
      .patch(dirty)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this._hydrate(s);
          this.saving.set(false);
          this.saveOk.set(true);
          this.toast.success('Store profile saved.', {
            subtitle: 'Your changes are live for the whole team.',
          });
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          const msg = extractApiError(err) ?? 'Could not save settings.';
          this.saveError.set(msg);
          this.toast.error('Could not save store profile.', { subtitle: msg });
        },
      });
  }

  private _hydrate(s: OrgSettings): void {
    this.form.reset({
      store_name: s.store_name,
      logo_url: s.logo_url,
      gst_number: s.gst_number,
      address_line1: s.address_line1,
      address_line2: s.address_line2,
      city: s.city,
      state: s.state,
      postal_code: s.postal_code,
      country: s.country,
      phone: s.phone,
      email: s.email,
      currency: s.currency,
      tax_rate: s.tax_rate,
      timezone: s.timezone,
      locale: s.locale,
    });
    this.reminderOffsets.set(s.appointment_reminder_offsets_minutes ?? [1440, 60]);
    this.reminderLoading.set(false);
  }
}
