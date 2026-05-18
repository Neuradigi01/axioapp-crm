import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { FurnitureAuthService, MeResponse } from '../auth/auth.service';
import { ProfileApiService } from './profile.service';

/**
 * `/user/profile` — self-service profile page.
 *
 * Two independent sub-forms:
 *   - Profile  (full_name, phone)            → PATCH /api/v1/users/me
 *   - Password (current, new, sign-out-others) → POST  /api/v1/users/me/password
 *
 * Each sub-form has its own submit button + success/error state. The
 * password sub-form is the only place a user can revoke other sessions
 * — if `sign_out_others` is ticked the backend revokes every open
 * `auth_sessions` row except the caller's own JWT.
 *
 * Email is intentionally shown read-only — changing email = inviting
 * a new account (step 2.5.6 wires that flow). Role / org membership
 * are admin-only and never exposed here.
 */
@Component({
  selector: 'app-profile-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './profile-page.component.html',
})
export class ProfilePageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ProfileApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly me = signal<MeResponse | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly profileForm = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    phone: [''],
  });
  protected readonly profileSaving = signal(false);
  protected readonly profileOk = signal(false);
  protected readonly profileError = signal<string | null>(null);

  protected readonly passwordForm = this.fb.nonNullable.group({
    current_password: ['', [Validators.required]],
    new_password: [
      '',
      [Validators.required, Validators.minLength(8), Validators.maxLength(255)],
    ],
    confirm_password: ['', [Validators.required]],
    sign_out_others: [false],
  });
  protected readonly passwordSaving = signal(false);
  protected readonly passwordOk = signal(false);
  protected readonly passwordError = signal<string | null>(null);

  constructor() {
    this.reload();
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
          this.loadError.set(this._extract(err) ?? 'Could not load profile.');
        },
      });
  }

  protected saveProfile(): void {
    if (this.profileForm.invalid || this.profileSaving()) return;
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
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.profileSaving.set(false);
          this.profileError.set(
            this._extract(err) ?? 'Could not save profile.',
          );
        },
      });
  }

  protected changePassword(): void {
    if (this.passwordSaving()) return;
    const raw = this.passwordForm.getRawValue();
    if (this.passwordForm.invalid) {
      this.passwordError.set('All fields are required, min 8 chars.');
      return;
    }
    if (raw.new_password !== raw.confirm_password) {
      this.passwordError.set('New password and confirmation do not match.');
      return;
    }

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
          this.passwordForm.reset({
            current_password: '',
            new_password: '',
            confirm_password: '',
            sign_out_others: false,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.passwordSaving.set(false);
          this.passwordError.set(
            this._extract(err) ?? 'Could not change password.',
          );
        },
      });
  }

  private _extract(err: HttpErrorResponse): string | null {
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
