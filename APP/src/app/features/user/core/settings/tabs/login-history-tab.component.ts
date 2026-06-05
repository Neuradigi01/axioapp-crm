import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';

import {
  LoginHistoryApiService,
  SessionRow,
} from '../services/login-history-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Settings → Login history tab. Reads `GET /api/v1/auth/sessions`,
 * renders the last 50 sessions (newest first) with the current JWT
 * marked "This session." Per-row Sign-out posts to
 * `POST /auth/sessions/{id}/revoke`; the current session can only be
 * ended via the regular logout flow (the backend rejects revoking it
 * here with 400).
 */
@Component({
  selector: 'app-settings-login-history-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  templateUrl: './login-history-tab.component.html',
})
export class LoginHistoryTabComponent {
  private readonly api = inject(LoginHistoryApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly sessions = signal<SessionRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly revokingId = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.sessions.set(res.sessions ?? []);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not load login history.',
          );
        },
      });
  }

  protected revoke(row: SessionRow): void {
    if (row.is_current || row.revoked_at) return;
    this.revokingId.set(row.id);
    this.api
      .revoke(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.revokingId.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.revokingId.set(null);
          this.error.set(
            extractApiError(err) ?? 'Could not sign out that session.',
          );
        },
      });
  }

  /** True when the row is still usable (not revoked and not expired). */
  protected isActive(row: SessionRow): boolean {
    if (row.revoked_at) return false;
    return new Date(row.expires_at).getTime() > Date.now();
  }
}
