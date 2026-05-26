/**
 * Settings → Integrations page. Owner-only (gated by
 * `settings.integrations.manage`). Replaces the old read-only
 * placeholder; Steps 7 + 8 build it out.
 *
 * Layout:
 *
 *   ┌─────────────────────────────────────────────────────┐
 *   │  Google Ads card                                    │
 *   ├─────────────────────────────────────────────────────┤
 *   │  Meta Ads card                                      │
 *   ├─────────────────────────────────────────────────────┤
 *   │  Dead-letter summary  (count + "view all" link to   │
 *   │  Step 8's full DLQ surface — Step 7 just shows the  │
 *   │  count to give Owners awareness)                    │
 *   └─────────────────────────────────────────────────────┘
 *
 * On init: reads `?status=…&reason=…` from the URL. Google's and
 * Meta's OAuth callbacks bounce here with one of:
 *   `google_connected` / `google_denied` / `google_error`
 *   `meta_connected`   / `meta_denied`   / `meta_error`
 * Shows a one-line banner accordingly, then refetches the
 * integrations list so each card re-renders from the new state.
 *
 * Loads `subscriptions` once + passes the array down to each card.
 * Each card filters to its own `integration_id` client-side — keeps
 * a single source of truth + makes toggle UX cheap (no per-toggle
 * refetch needed, just emit `changed` and the page refetches).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { GoogleCardComponent } from './google-card.component';
import { MetaCardComponent } from './meta-card.component';
import {
  Integration,
  IntegrationsApiService,
  IntegrationSubscription,
} from './integrations-api.service';


type CallbackStatus =
  | 'google_connected'
  | 'google_denied'
  | 'google_error'
  | 'meta_connected'
  | 'meta_denied'
  | 'meta_error';


@Component({
  selector: 'app-settings-integrations-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GoogleCardComponent, MetaCardComponent, LucideAngularModule],
  templateUrl: './integrations-page.component.html',
})
export class IntegrationsPageComponent {
  private readonly api = inject(IntegrationsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  // --- top-level signals --------------------------------------------

  protected readonly integrations = signal<Integration[]>([]);
  protected readonly subscriptions = signal<IntegrationSubscription[]>([]);
  protected readonly dlqTotal = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  /** OAuth-callback banner. Set from query-string on init; cleared
   *  when the user dismisses or after 8s (timeout in the template's
   *  CSS-only path would be nicer, but a setTimeout in the
   *  constructor is fine for one-shot UX). */
  protected readonly callbackBanner = signal<{
    kind: 'success' | 'warn' | 'error';
    title: string;
    detail: string | null;
  } | null>(null);

  // --- derived ------------------------------------------------------

  protected readonly google = computed(
    () =>
      this.integrations().find((i) => i.provider === 'google_ads') ?? null,
  );
  protected readonly meta = computed(
    () =>
      this.integrations().find((i) => i.provider === 'meta_ads') ?? null,
  );

  constructor() {
    this._readCallbackQuery();
    this._refresh();
  }

  // --- handlers -----------------------------------------------------

  /** Called by either card after a successful Connect / Disconnect /
   *  Subscribe / Unsubscribe so the page re-fetches and every card
   *  picks up the new state in a single round trip. */
  onCardChanged(): void {
    this._refresh();
  }

  dismissBanner(): void {
    this.callbackBanner.set(null);
  }

  // --- internals ----------------------------------------------------

  private _refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    forkJoin({
      integrations: this.api.list(),
      subscriptions: this.api.listSubscriptions(),
      dlq: this.api.listDlq(1, 1),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ integrations, subscriptions, dlq }) => {
          this.integrations.set(integrations);
          this.subscriptions.set(subscriptions);
          this.dlqTotal.set(dlq.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }

  private _readCallbackQuery(): void {
    const params = this.route.snapshot.queryParamMap;
    const status = params.get('status') as CallbackStatus | null;
    if (!status) return;
    const reason = params.get('reason');
    this.callbackBanner.set(this._bannerFor(status, reason));
    // Strip the query params so a reload doesn't re-banner. Router
    // navigation preserves the path; `queryParams: {}` + `queryParamsHandling:
    // ''` clears them.
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {},
      replaceUrl: true,
    });
  }

  private _bannerFor(
    status: CallbackStatus,
    reason: string | null,
  ): { kind: 'success' | 'warn' | 'error'; title: string; detail: string | null } {
    switch (status) {
      case 'google_connected':
        return {
          kind: 'success',
          title: 'Google Ads connected.',
          detail: 'Pick the Lead Forms below to start receiving leads.',
        };
      case 'meta_connected':
        return {
          kind: 'success',
          title: 'Meta connected.',
          detail:
            'Subscribe to a Page below to start receiving its Lead Ads.',
        };
      case 'google_denied':
      case 'meta_denied':
        return {
          kind: 'warn',
          title: 'Connect cancelled.',
          detail: reason
            ? `Reason: ${reason}`
            : 'Re-try the Connect button to authorise again.',
        };
      case 'google_error':
      case 'meta_error':
        return {
          kind: 'error',
          title: 'Connect failed.',
          detail: reason
            ? `Reason: ${reason}`
            : 'Try again, or check the backend logs.',
        };
    }
  }
}
