/**
 * Settings → Integrations → Google Calendar card (per-user).
 *
 * Three view states selected by ``status.connected`` + ``status.last_error``:
 *
 *   - **Not connected** (no row) → "Sync your appointments to your
 *     Google Calendar" + Connect CTA.
 *   - **Connected**   → "Connected as <email>" + last-synced label +
 *     Disconnect CTA.
 *   - **Reconnect needed** (row exists but ``last_error`` populated
 *     from a revoke / upstream failure) → warning banner with the
 *     underlying reason + Reconnect CTA (same target as Connect —
 *     Step 2's ``start_authorize`` always uses ``prompt=consent``).
 *
 * The card polls ``/status`` every 5s while an OAuth attempt is in
 * flight (a window flag we set right before ``window.location.assign``)
 * so the connected state materialises the moment the browser bounces
 * back. Between OAuth attempts we fetch once on mount + refetch when
 * the parent bumps a ``refresh`` counter.
 */
import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { GoogleCalendarStatus, IntegrationsApiService } from './integrations-api.service';

const POLL_INTERVAL_MS = 5000;

@Component({
  selector: 'app-google-calendar-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DatePipe, LucideAngularModule],
  templateUrl: './google-calendar-card.component.html',
})
export class GoogleCalendarCardComponent {
  /** Parent bumps this whenever it wants the card to refetch — e.g.
   *  after the callback banner processes a ``?status=...`` param. */
  readonly refreshTick = input<number>(0);

  /** Emitted after Connect / Disconnect so the parent can refresh any
   *  shared status banner. */
  readonly changed = output<void>();

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly status = signal<GoogleCalendarStatus | null>(null);
  protected readonly loading = signal<boolean>(true);
  protected readonly inlineError = signal<string | null>(null);

  /** Minutes until the current short-lived access token expires.
   *  `null` when not connected / no expiry stamp. Google
   *  auto-refreshes via the refresh token on healthy grants, so
   *  this ticks forward silently — the countdown only matters if
   *  the refresh path is broken (revoked grant / disabled app),
   *  which coincides with `last_error` populating. */
  protected readonly minutesToExpiry = computed<number | null>(() => {
    const exp = this.status()?.access_token_expires_at;
    if (!exp) return null;
    const t = new Date(exp).getTime();
    if (isNaN(t)) return null;
    return Math.round((t - Date.now()) / 60_000);
  });

  /** Human "10 min" / "2 hr" / "1 day" formatted `minutesToExpiry`.
   *  Only ever rendered on connected accounts. */
  protected readonly expiryLabel = computed<string | null>(() => {
    const m = this.minutesToExpiry();
    if (m === null) return null;
    if (m <= 0) return 'expired';
    if (m < 60) return `${m} min`;
    const hours = Math.round(m / 60);
    if (hours < 48) return `${hours} hr`;
    const days = Math.round(hours / 24);
    return `${days} day${days === 1 ? '' : 's'}`;
  });

  /** True iff Google reported an auth-related error (revoked grant,
   *  invalid_grant, insufficient_scope). Drives the RED reconnect
   *  banner — this is what would've caught the user's silent Aug 14
   *  revocation before appointment sync failed. */
  protected readonly authRevoked = computed<boolean>(() => {
    const err = this.status()?.last_error?.toLowerCase() ?? '';
    if (!err) return false;
    return (
      err.includes('invalid_grant') ||
      err.includes('revoked') ||
      err.includes('unauthorized') ||
      err.includes('token has been expired') ||
      err.includes('insufficient')
    );
  });

  /** Windowed poll — flips to true right before the SPA navigates to
   *  Google's consent screen, false after we get the first status
   *  response with ``connected=true``. The 5s poll keeps running
   *  while true so the connected state appears the moment the user
   *  bounces back. */
  protected readonly awaitingOAuth = signal<boolean>(false);

  private pollHandle: number | null = null;

  constructor() {
    // Initial fetch + reactive refetch on the parent's refresh signal.
    effect(() => {
      void this.refreshTick();
      this.fetchStatus();
    });

    this.destroyRef.onDestroy(() => this.clearPoll());
  }

  // --- Actions -----------------------------------------------------

  connect(): void {
    this.inlineError.set(null);
    this.awaitingOAuth.set(true);
    this.startPoll();
    this.api
      .startGoogleCalendarAuthorize()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.awaitingOAuth.set(false);
          this.clearPoll();
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  reconnect(): void {
    this.connect();
  }

  disconnect(): void {
    if (
      !confirm(
        'Disconnect Google Calendar? Appointments will stop syncing to your calendar until you reconnect.',
      )
    ) {
      return;
    }
    this.inlineError.set(null);
    this.api
      .disconnectGoogleCalendar()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.status.set({
            connected: false,
            google_email: null,
            last_error: null,
            last_synced_at: null,
            scopes_granted: [],
            access_token_expires_at: null,
          });
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  // --- Polling -----------------------------------------------------

  private fetchStatus(): void {
    this.loading.set(true);
    this.api
      .getGoogleCalendarStatus()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.status.set(s);
          this.loading.set(false);
          if (s.connected && this.awaitingOAuth()) {
            this.awaitingOAuth.set(false);
            this.clearPoll();
            this.changed.emit();
          }
        },
        error: () => {
          this.loading.set(false);
          // Non-fatal — leave whatever state the card had before.
        },
      });
  }

  private startPoll(): void {
    this.clearPoll();
    this.pollHandle = window.setInterval(() => {
      this.fetchStatus();
    }, POLL_INTERVAL_MS);
  }

  private clearPoll(): void {
    if (this.pollHandle !== null) {
      window.clearInterval(this.pollHandle);
      this.pollHandle = null;
    }
  }
}
