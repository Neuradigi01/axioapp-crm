import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';

import { FurnitureAuthService } from '../../auth/auth.service';
import { TwoFactorApiService } from '../services/two-factor-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Settings → Two-factor tab. Read-only status surface for the
 * settings-page track.
 *
 * In-dashboard TOTP enrol + disable is intentionally NOT shipped here:
 * those flows need ActionToken re-auth proofs + TOTP secret rotation
 * and are scoped into a focused follow-up track
 * (`tasks/two-factor-self-service/`). For now, enrol path is "Sign out
 * → sign in → 2FA enforcement screen" — the existing `accounts/two-factor/`
 * component owns the enrol UX.
 */
@Component({
  selector: 'app-settings-two-factor-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './two-factor-tab.component.html',
})
export class TwoFactorTabComponent {
  private readonly api = inject(TwoFactorApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly enabled = signal(false);
  protected readonly method = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly signingOut = signal(false);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .status()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.enabled.set(res.enabled);
          this.method.set(res.method);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load two-factor status.');
        },
      });
  }

  /**
   * Logs the user out and routes to `/accounts/login`. The existing
   * post-login 2FA enforcement screen at `features/accounts/two-factor/`
   * is where TOTP / Email OTP / SMS OTP enrol happens.
   */
  protected manageOnNextLogin(): void {
    if (this.signingOut()) return;
    this.signingOut.set(true);
    this.auth
      .logout()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.router.navigate(['/accounts/login']),
        error: () => {
          // Logout endpoint failures shouldn't strand the user — clear
          // local storage anyway and bounce.
          this.router.navigate(['/accounts/login']);
        },
      });
  }
}
