import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, OrgSummary } from '../../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';
import {
  OrgSettings,
  SettingsApiService,
} from '../settings-api.service';

/**
 * Store Profile tab â€” the meat of OrgSettings. Logo, store name,
 * GST, full address, phone, email, currency, tax_rate, timezone,
 * locale. Submits only the dirty keys via PATCH (strict-key on the
 * backend side too).
 */
@Component({
  selector: 'app-settings-store-profile-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './store-profile-tab.component.html',
})
export class StoreProfileTabComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(SettingsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly saveOk = signal(false);
  /** Read-only org identity surfaced above the editable form (DR.5 + 2.5.4). */
  protected readonly org = signal<OrgSummary | null>(null);
  /** Gate the Save button on `settings.write`. Read access alone keeps the
   * form viewable but unsubmittable â€” same UX shape as the Roles tab. */
  protected readonly canWrite = signal(false);

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
          this.loadError.set(
            extractApiError(err) ?? 'Could not load settings.',
          );
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
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(
            extractApiError(err) ?? 'Could not save settings.',
          );
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
  }

}
