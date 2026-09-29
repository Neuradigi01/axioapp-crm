import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, MeResponse } from '../../auth/auth.service';
import { ProfileApiService } from '../../profile/profile.service';
import { commonValidators } from '../../shared/validators';
import { matchFieldValidator } from '@shared/validators/custom-validators';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';

/**
 * Settings → Profile tab — self-service profile + password management.
 *
 * Two independent sub-forms (lifted from the now-removed standalone
 * `/user/profile` page):
 *   - Profile  (full_name, phone)              → PATCH /api/v1/users/me
 *   - Password (current, new, sign-out-others) → POST  /api/v1/users/me/password
 *
 * The password sub-form is the only place a user can revoke other
 * sessions — `sign_out_others` revokes every open `auth_sessions` row
 * except the caller's own JWT. Email is shown read-only.
 */
@Component({
  selector: 'app-settings-profile-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './profile-tab.component.html',
})
export class ProfileTabComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ProfileApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly me = signal<MeResponse | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly profileForm = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, commonValidators.name, Validators.maxLength(255)]],
    phone: ['', [commonValidators.phone()]],
  });
  protected readonly profileSaving = signal(false);
  protected readonly profileOk = signal(false);
  protected readonly profileError = signal<string | null>(null);

  protected readonly passwordForm = this.fb.nonNullable.group({
    current_password: ['', [Validators.required, Validators.maxLength(128)]],
    new_password: ['', [Validators.required, commonValidators.password]],
    confirm_password: [
      '',
      [Validators.required, Validators.maxLength(128), matchFieldValidator('new_password')],
    ],
    sign_out_others: [false],
  });
  protected readonly passwordSaving = signal(false);
  protected readonly passwordOk = signal(false);
  protected readonly passwordError = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  /** Error text under a profile input once touched, or null. */
  protected profileFieldError(name: 'full_name' | 'phone'): string | null {
    const ctrl = this.profileForm.controls[name];
    if (!ctrl.touched || !ctrl.errors) return null;
    if (ctrl.errors['required']) return 'Full name is required.';
    if (ctrl.errors['maxlength']) return 'Keep it under 255 characters.';
    if (ctrl.errors['nameInvalid']) return `Full name: ${ctrl.errors['nameInvalid']}.`;
    if (ctrl.errors['phoneInvalid']) return 'Include the country code, e.g. +919876543210.';
    return null;
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => {
          this.me.set(me);
          this.profileForm.reset({
            full_name: me.full_name,
            phone: me.phone ?? '',
          });
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          const msg = extractApiError(err) ?? 'Could not load profile.';
          this.loadError.set(msg);
          this.toast.error('Could not load profile', { subtitle: msg });
        },
      });
  }

  protected saveProfile(): void {
    if (this.profileSaving()) return;
    if (this.profileForm.invalid) {
      this.profileForm.markAllAsTouched();
      const fields = [
        this.profileForm.controls.full_name.invalid ? 'Full name' : null,
        this.profileForm.controls.phone.invalid ? 'Phone' : null,
      ].filter((f): f is string => f !== null);
      this.toast.warn('Could not save profile', { subtitle: `Check: ${fields.join(', ')}.` });
      return;
    }
    if (this.profileForm.pristine) {
      this.toast.info('No changes to save');
      return;
    }
    const raw = this.profileForm.getRawValue();
    const phone = raw.phone.trim();
    this.profileSaving.set(true);
    this.profileError.set(null);
    this.profileOk.set(false);

    this.api
      .updateMe({
        full_name: raw.full_name.trim(),
        phone: phone.length > 0 ? phone : null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.profileSaving.set(false);
          this.profileOk.set(true);
          this.toast.success('Profile updated', { subtitle: raw.full_name.trim() });
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.profileSaving.set(false);
          const msg = extractApiError(err) ?? 'Could not save profile.';
          this.profileError.set(msg);
          this.toast.error('Could not save profile', { subtitle: msg });
        },
      });
  }

  protected changePassword(): void {
    if (this.passwordSaving()) return;
    if (this.passwordForm.invalid) {
      this.passwordForm.markAllAsTouched();
      this.passwordError.set('Please fix the highlighted fields.');
      this.toast.warn('Could not change password', {
        subtitle: 'Please fix the highlighted fields.',
      });
      return;
    }
    const raw = this.passwordForm.getRawValue();

    this.passwordSaving.set(true);
    this.passwordError.set(null);
    this.passwordOk.set(false);

    this.api
      .changePassword({
        current_password: raw.current_password,
        new_password: raw.new_password,
        sign_out_others: raw.sign_out_others,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.passwordSaving.set(false);
          this.passwordOk.set(true);
          this.toast.success('Password changed', {
            subtitle: raw.sign_out_others ? 'Your other sessions were signed out.' : null,
          });
          this.passwordForm.reset({
            current_password: '',
            new_password: '',
            confirm_password: '',
            sign_out_others: false,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.passwordSaving.set(false);
          const msg = extractApiError(err) ?? 'Could not change password.';
          this.passwordError.set(msg);
          this.toast.error('Could not change password', { subtitle: msg });
        },
      });
  }
}
