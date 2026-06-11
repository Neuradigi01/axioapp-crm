import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { SubscriptionStateService } from '../services/subscription-state.service';

/** How often to re-fetch `/subscriptions/current`. */
const POLL_INTERVAL_MS = 2_000;
/** Maximum total wait before giving up and showing the slow-webhook copy. */
const TOTAL_TIMEOUT_MS = 30_000;
/** Pause before navigating away after we see `active` — lets the
 *  brief "Completed" frame paint so the success isn't jarring. */
const SUCCESS_NAVIGATE_DELAY_MS = 400;

type PageStatus = 'polling' | 'completed' | 'timeout';

/**
 * Landing page Stripe Checkout redirects to after a successful upgrade.
 *
 * Stripe's redirect happens immediately after payment, but our
 * subscription status only flips when the Step 13.b webhook lands
 * `checkout.session.completed`. That takes 1-5 seconds usually. We
 * poll `GET /subscriptions/current` every 2 s for up to 30 s; on the
 * first response with `status === 'active'`, we navigate the user
 * back to `/user/subscription?upgraded=true` so the billing page
 * can render the success toast.
 *
 * Timeout copy points the user at a manual refresh in case the
 * webhook is genuinely delayed (rare; Stripe's SLA is best-effort).
 */
@Component({
  selector: 'crm-upgrade-success-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './upgrade-success.page.html',
  styleUrl: './upgrade-success.page.css',
})
export class UpgradeSuccessPage implements OnInit {
  private readonly state = inject(SubscriptionStateService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly status = signal<PageStatus>('polling');

  private startedAt = 0;
  private pollHandle: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.startedAt = Date.now();

    // Fire an immediate refresh + check; the interval below covers
    // the steady-state polling.
    this.state.refresh();
    this.checkStatus();

    this.pollHandle = setInterval(() => {
      this.state.refresh();
      this.checkStatus();
    }, POLL_INTERVAL_MS);

    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  private checkStatus(): void {
    if (this.status() !== 'polling') return;
    const sub = this.state.current();
    if (sub !== null && sub.status === 'active') {
      this.status.set('completed');
      this.stopPolling();
      setTimeout(() => {
        this.router.navigateByUrl(
          '/user/subscription?upgraded=true',
        );
      }, SUCCESS_NAVIGATE_DELAY_MS);
      return;
    }
    if (Date.now() - this.startedAt >= TOTAL_TIMEOUT_MS) {
      this.status.set('timeout');
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.pollHandle === null) return;
    clearInterval(this.pollHandle);
    this.pollHandle = null;
  }
}
