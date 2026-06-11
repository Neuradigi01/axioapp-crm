/**
 * Connect-account card — Gmail + Microsoft buttons + DPDP consent
 * banner.
 *
 * The buttons call `authorizeGmail()` / `authorizeMicrosoft()` which
 * return `{url: string}`; the click handler does
 * `window.location.assign(url)` to navigate the top-level browser.
 * The backend's `/callback` will redirect back to
 * `/user/settings/email-accounts?status=…` so the parent tab can
 * show a toast and refresh the list.
 *
 * The DPDP / GDPR consent callout is a one-time acknowledgment kept
 * per-user in `localStorage` — this is acknowledgment, not consent-
 * of-record. The OAuth grant itself is the legal consent record;
 * the banner just makes the privacy implications visible before the
 * redirect kicks off.
 *
 * Emits `error` when the authorize call fails so the parent can show
 * an inline error.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { EmailAccountsApiService } from '../../services/email-accounts-api.service';


const _CONSENT_STORAGE_KEY = 'email-accounts:consent-acknowledged';


@Component({
  selector: 'app-connect-account-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './connect-account-card.component.html',
})
export class ConnectAccountCardComponent {
  private readonly api = inject(EmailAccountsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly error = output<string>();

  /** Provider currently mid-redirect. Both buttons disable while one
   *  is in flight so a double-click can't fire two consent windows. */
  protected readonly redirecting = signal<'gmail' | 'microsoft' | null>(
    null,
  );

  protected readonly consentAcknowledged = signal<boolean>(
    this._readConsent(),
  );

  /** Consent banner is visible when the user hasn't dismissed it AND
   *  they don't already have a connected account (parent passes that
   *  signal in via `hasAnyAccount` — when true the banner is noise). */
  readonly hasAnyAccount = computed(() => false);

  acknowledgeConsent(): void {
    try {
      localStorage.setItem(_CONSENT_STORAGE_KEY, '1');
    } catch {
      // Private-mode browsers reject localStorage writes silently;
      // session-only acknowledgment is still a usable UX.
    }
    this.consentAcknowledged.set(true);
  }

  connectGmail(): void {
    if (this.redirecting() !== null) return;
    this.redirecting.set('gmail');
    this.api
      .authorizeGmail()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          // Top-level navigation — the OAuth flow needs a real browser
          // GET, not an XHR.
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.redirecting.set(null);
          this.error.emit(extractApiError(err));
        },
      });
  }

  connectMicrosoft(): void {
    if (this.redirecting() !== null) return;
    this.redirecting.set('microsoft');
    this.api
      .authorizeMicrosoft()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.redirecting.set(null);
          this.error.emit(extractApiError(err));
        },
      });
  }

  private _readConsent(): boolean {
    try {
      return localStorage.getItem(_CONSENT_STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  }
}
