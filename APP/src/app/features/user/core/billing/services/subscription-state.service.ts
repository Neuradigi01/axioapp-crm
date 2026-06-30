import { DestroyRef, Injectable, computed, effect, inject, signal } from '@angular/core';

import { BillingApiService } from './billing-api.service';
import { SubscriptionCurrent } from '../types/subscription.types';

/** How often we re-fetch when the org is on a trial.
 *
 *  Five minutes is the spec's number — the countdown only needs
 *  minute-level precision, and the cost is one tiny HTTP call per
 *  active session per 5 minutes.
 */
const TRIAL_POLL_INTERVAL_MS = 5 * 60 * 1000;

/**
 * Global app-state signal over `GET /subscriptions/current`.
 *
 * Single source of truth for the trial banner (Step 15), the billing
 * settings page (Step 16), and the locked-feature tile (Step 18).
 * `providedIn: 'root'` guarantees one instance across the app — wrong
 * scoping would multiply the API calls and produce stale views when
 * one component mutates and another lags.
 *
 * Lifecycle:
 *   - First consumer's `inject(...)` triggers an initial `refresh()`.
 *   - When `status === 'trialing'`, an interval polls every 5 minutes
 *     so the countdown stays fresh as midnight ticks past.
 *   - `notifyChanged()` is the public hook the upgrade-flow code
 *     (Step 17's checkout success) calls to force an immediate refresh.
 */
@Injectable({ providedIn: 'root' })
export class SubscriptionStateService {
  private readonly api = inject(BillingApiService);
  private readonly destroyRef = inject(DestroyRef);

  private readonly _current = signal<SubscriptionCurrent | null>(null);
  private readonly _isLoading = signal<boolean>(false);
  private readonly _loadError = signal<boolean>(false);

  /** Most-recent payload from the API, or `null` before the first fetch
   *  resolves / after a hard failure. */
  readonly current = this._current.asReadonly();
  readonly isLoading = this._isLoading.asReadonly();
  readonly loadError = this._loadError.asReadonly();

  /** Convenience selector — banner uses this to decide whether to
   *  render at all. */
  readonly status = computed(() => this._current()?.status ?? null);

  private pollHandle: ReturnType<typeof setInterval> | null = null;

  constructor() {
    // Kick off the first fetch as soon as anyone injects the service.
    this.refresh();

    // Auto-manage the polling interval. The effect re-runs whenever
    // `status` changes — turning the poll on for `trialing`, off for
    // anything else.
    effect(() => {
      const s = this.status();
      if (s === 'trialing') {
        this.startTrialPoll();
      } else {
        this.stopTrialPoll();
      }
    });

    this.destroyRef.onDestroy(() => this.stopTrialPoll());
  }

  /** Force a re-fetch. Safe to call from anywhere (upgrade modal
   *  success, plan-change form submit, etc.). */
  refresh(): void {
    this._isLoading.set(true);
    this._loadError.set(false);
    this.api.getCurrent().subscribe({
      next: (sub) => {
        this._current.set(sub);
        this._isLoading.set(false);
      },
      error: () => {
        // Keep the prior snapshot on transient errors — better UX
        // than a flicker to "unavailable" while the retry interceptor
        // re-attempts.
        this._loadError.set(true);
        this._isLoading.set(false);
      },
    });
  }

  /** Re-fetch after a state-changing action elsewhere in the app.
   *  Step 17's checkout success calls this. */
  notifyChanged(): void {
    this.refresh();
  }

  private startTrialPoll(): void {
    if (this.pollHandle !== null) return;
    this.pollHandle = setInterval(() => this.refresh(), TRIAL_POLL_INTERVAL_MS);
  }

  private stopTrialPoll(): void {
    if (this.pollHandle === null) return;
    clearInterval(this.pollHandle);
    this.pollHandle = null;
  }
}
