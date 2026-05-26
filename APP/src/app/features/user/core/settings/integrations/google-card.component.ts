/**
 * Settings → Integrations → Google Ads card.
 *
 * Three view states selected by the integration's `status`:
 *
 *  - `null` (no row) or `disconnected` → "Not connected" + Connect CTA.
 *  - `connected` → account email + accessible Ads accounts; expand
 *    each account to its Lead Forms; per-form Subscribe toggle;
 *    webhook URL with copy button; Disconnect CTA.
 *  - `expired` or `error` → "Reconnect required" banner with the
 *    `last_error` (when present) + Reconnect CTA (same target as
 *    Connect — Step 2's `start_authorize` always uses `prompt=consent`
 *    so reconnect mints fresh tokens).
 *
 * Optimistic subscribe-toggle UX: clicking flips the local signal
 * immediately, then POSTs. On failure the signal reverts and a
 * toast surfaces the reason.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  GoogleAdsAccount,
  GoogleLeadForm,
  Integration,
  IntegrationsApiService,
  IntegrationSubscription,
} from './integrations-api.service';


@Component({
  selector: 'app-google-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './google-card.component.html',
})
export class GoogleCardComponent {
  /** The Google integration row, or null when the org never connected. */
  readonly integration = input<Integration | null>(null);
  /** All subscriptions in the org — the card filters to its own. */
  readonly subscriptions = input<IntegrationSubscription[]>([]);

  /** Emitted after Connect / Disconnect / Subscribe / Unsubscribe
   *  succeeds so the parent can refetch the integrations list +
   *  subscriptions and re-render every card consistently. */
  readonly changed = output<void>();
  /** Toast-like inline error for failed actions (network errors,
   *  Google API rejections). Surfaced at the card top, not in a
   *  global toast — keeps the failure context next to the action. */
  readonly inlineError = signal<string | null>(null);

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  // --- view state --------------------------------------------------

  /** Loaded on Connect-state init; lazy on Disconnect → stays empty. */
  protected readonly accounts = signal<GoogleAdsAccount[]>([]);
  protected readonly accountsLoaded = signal(false);
  protected readonly accountsLoading = signal(false);

  /** Map customer_id → forms, populated when the user expands the
   *  account row. Keeps the initial Connect view fast (one API call
   *  for accounts only). */
  protected readonly formsByAccount = signal<Record<string, GoogleLeadForm[]>>(
    {},
  );
  protected readonly expandedAccounts = signal<Set<string>>(new Set());
  protected readonly formsLoadingFor = signal<string | null>(null);

  /** In-flight subscribe/unsubscribe key (form_id) so we can disable
   *  the toggle while the request resolves. */
  protected readonly toggleInFlightFor = signal<string | null>(null);

  /** Convenience computed views. */
  protected readonly isConnected = computed(
    () => this.integration()?.status === 'connected',
  );
  protected readonly needsReconnect = computed(() => {
    const s = this.integration()?.status;
    return s === 'expired' || s === 'error';
  });
  protected readonly webhookUrl = computed(
    () => this.integration()?.webhook_url ?? null,
  );

  /** Active subscriptions for THIS integration, keyed by form_id
   *  for O(1) toggle-state lookup in the template. */
  protected readonly subscriptionsByForm = computed(() => {
    const id = this.integration()?.id;
    const map: Record<string, IntegrationSubscription> = {};
    if (!id) return map;
    for (const s of this.subscriptions()) {
      if (s.integration_id === id) {
        map[s.external_form_id] = s;
      }
    }
    return map;
  });

  // --- actions -----------------------------------------------------

  /** Start OAuth: XHR to /authorize for the consent URL, then
   *  navigate the browser to it. The XHR is needed because the
   *  /authorize endpoint is JWT-gated and a top-level GET wouldn't
   *  carry the Bearer header (only the interceptor adds it on XHRs).
   */
  connect(): void {
    this.inlineError.set(null);
    this.api
      .startGoogleAuthorize()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  /** Same handler as Connect — Step-2's `start_authorize` always
   *  uses `prompt=consent`, so Google re-issues a refresh token. */
  reconnect(): void {
    this.connect();
  }

  disconnect(): void {
    if (!confirm('Disconnect Google Ads? Active webhook subscriptions stop receiving leads.')) {
      return;
    }
    this.inlineError.set(null);
    this.api
      .disconnect('google_ads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.accounts.set([]);
          this.accountsLoaded.set(false);
          this.formsByAccount.set({});
          this.expandedAccounts.set(new Set());
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  loadAccounts(): void {
    if (this.accountsLoaded() || this.accountsLoading()) return;
    if (!this.isConnected()) return;
    this.accountsLoading.set(true);
    this.api
      .listGoogleAccounts()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.accounts.set(rows);
          this.accountsLoaded.set(true);
          this.accountsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.accountsLoading.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  toggleAccountExpansion(customerId: string): void {
    const next = new Set(this.expandedAccounts());
    if (next.has(customerId)) {
      next.delete(customerId);
      this.expandedAccounts.set(next);
      return;
    }
    next.add(customerId);
    this.expandedAccounts.set(next);
    // Lazy-load this account's forms only on first expansion.
    if (this.formsByAccount()[customerId]) return;
    this.formsLoadingFor.set(customerId);
    this.api
      .listGoogleForms(customerId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.formsByAccount.update((m) => ({ ...m, [customerId]: rows }));
          this.formsLoadingFor.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.formsLoadingFor.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  /** Subscribe or unsubscribe the form, depending on current state.
   *  Optimistic: parent's `subscriptions` signal is the source of
   *  truth; we emit `changed` after the backend round trip to refetch. */
  toggleSubscribe(form: GoogleLeadForm): void {
    const integration = this.integration();
    if (!integration) return;
    if (this.toggleInFlightFor()) return;
    this.toggleInFlightFor.set(form.form_id);
    this.inlineError.set(null);

    const existing = this.subscriptionsByForm()[form.form_id];
    const done = () => {
      this.toggleInFlightFor.set(null);
      this.changed.emit();
    };
    const fail = (err: HttpErrorResponse) => {
      this.toggleInFlightFor.set(null);
      this.inlineError.set(extractApiError(err));
    };
    // Split the branch so TypeScript narrows each subscribe() call to
    // its own observer-shape (Observable<void> for delete vs
    // Observable<IntegrationSubscription> for create — the union
    // confuses the .subscribe overload resolver).
    if (existing) {
      this.api
        .deleteSubscription(existing.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ next: done, error: fail });
    } else {
      this.api
        .createSubscription({
          integration_id: integration.id,
          external_form_id: form.form_id,
          external_form_label: form.name,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ next: done, error: fail });
    }
  }

  copyWebhookUrl(): void {
    const url = this.webhookUrl();
    if (!url) return;
    void navigator.clipboard.writeText(url).catch(() => {
      this.inlineError.set('Could not copy to clipboard.');
    });
  }
}
