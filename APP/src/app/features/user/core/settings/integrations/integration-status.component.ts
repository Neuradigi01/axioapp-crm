/**
 * Step 8 — Integrations dashboard panel.
 *
 * Sits above the provider cards. Two tiles (Google + Meta) showing
 * connection status + last-delivery timestamp + 24h accepted/failed
 * counters, plus a single "X failures need attention" banner when
 * `dlq_open_total > 0`.
 *
 * Polls `/api/v1/integrations/status` every 30s — cheap, since the
 * status endpoint hits indexed audit-log rows + a single COUNT on
 * `integration_dlq`. The poll is paused while the document is hidden
 * (tab switched away) to avoid wasted work.
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
import { Subscription, interval } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  IntegrationsApiService,
  IntegrationStatusResponse,
  ProviderDeliveryStatus,
} from './integrations-api.service';

const POLL_INTERVAL_MS = 30_000;

@Component({
  selector: 'app-integration-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './integration-status.component.html',
})
export class IntegrationStatusComponent {
  /** Emitted when the user clicks the DLQ banner — parent toggles
   *  the inline DLQ list visibility. */
  readonly openDlq = output<void>();

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly status = signal<IntegrationStatusResponse | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly providers = computed(() => this.status()?.providers ?? []);
  protected readonly dlqOpenTotal = computed(() => this.status()?.dlq_open_total ?? 0);

  private _pollSubscription: Subscription | null = null;
  private _visibilityHandler: (() => void) | null = null;

  constructor() {
    this._refresh();
    this._startPolling();
    this._bindVisibility();
    this.destroyRef.onDestroy(() => this._stopPolling());
  }

  // --- public helpers used by the template -------------------------

  /** Render a `last_delivery_at` ISO string as "4 minutes ago" /
   *  "2 hours ago" / "—" (never). Local-string is good enough for
   *  Owners; no i18n yet. */
  protected formatRelative(iso: string | null): string {
    if (!iso) return '—';
    const then = new Date(iso).getTime();
    if (isNaN(then)) return '—';
    const seconds = Math.floor((Date.now() - then) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  protected providerLabel(p: ProviderDeliveryStatus['provider']): string {
    return p === 'google_ads' ? 'Google Ads' : 'Meta Ads';
  }

  protected statusDotClass(s: ProviderDeliveryStatus['status']): string {
    switch (s) {
      case 'connected':
        return 'bg-emerald-500';
      case 'expired':
        return 'bg-amber-500';
      case 'error':
        return 'bg-rose-500';
      default:
        return 'bg-zinc-400';
    }
  }

  protected statusLabel(s: ProviderDeliveryStatus['status']): string {
    switch (s) {
      case 'connected':
        return 'Connected';
      case 'expired':
        return 'Expired';
      case 'error':
        return 'Error';
      default:
        return 'Not connected';
    }
  }

  onOpenDlq(): void {
    this.openDlq.emit();
  }

  // --- internals ---------------------------------------------------

  private _refresh(): void {
    this.api
      .getStatus()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.status.set(res);
          this.loading.set(false);
          this.error.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err));
        },
      });
  }

  private _startPolling(): void {
    if (this._pollSubscription) return;
    this._pollSubscription = interval(POLL_INTERVAL_MS)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (typeof document === 'undefined' || !document.hidden) {
          this._refresh();
        }
      });
  }

  private _stopPolling(): void {
    this._pollSubscription?.unsubscribe();
    this._pollSubscription = null;
    if (this._visibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this._visibilityHandler);
      this._visibilityHandler = null;
    }
  }

  /** Refresh immediately when the user returns to the tab — avoids
   *  showing a 30-second-stale snapshot after a long hide. */
  private _bindVisibility(): void {
    if (typeof document === 'undefined') return;
    this._visibilityHandler = () => {
      if (!document.hidden) this._refresh();
    };
    document.addEventListener('visibilitychange', this._visibilityHandler);
  }
}
