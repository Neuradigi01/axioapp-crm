import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, OrgSummary } from '../../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
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
        },
        error: (err: HttpErrorResponse) => {
          this.reminderSaving.set(false);
          this.reminderError.set(extractApiError(err) ?? 'Could not save reminder settings.');
        },
      });
  }

  protected readonly form = this.fb.group({
    store_name: this.fb.control<string | null>(null),
    logo_url: this.fb.control<string | null>(null),
    gst_number: this.fb.control<string | null>(null),
    address_line1: this.fb.control<string | null>(null),
    address_line2: this.fb.control<string | null>(null),
    city: this.fb.control<string | null>(null),
    state: this.fb.control<string | null>(null),
    postal_code: this.fb.control<string | null>(null),
    country: this.fb.control<string | null>(null),
    phone: this.fb.control<string | null>(null),
    email: this.fb.control<string | null>(null),
    currency: this.fb.control<string>('INR', { nonNullable: true }),
    tax_rate: this.fb.control<string>('18.00', { nonNullable: true }),
    timezone: this.fb.control<string>('Asia/Kolkata', { nonNullable: true }),
    locale: this.fb.control<string>('en-IN', { nonNullable: true }),
  });

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
          this.loadError.set(extractApiError(err) ?? 'Could not load settings.');
        },
      });
  }

  protected save(): void {
    if (!this.canWrite()) return;
    this.saving.set(true);
    this.saveError.set(null);
    this.saveOk.set(false);

    // Only send dirty controls so we honor the strict-key PATCH on
    // the backend (and don't accidentally re-write defaults).
    const dirty: Record<string, unknown> = {};
    for (const [key, ctrl] of Object.entries(this.form.controls)) {
      if (ctrl.dirty) dirty[key] = ctrl.value;
    }
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
