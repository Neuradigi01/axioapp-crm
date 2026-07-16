/**
 * Settings → Integrations → Meta (Facebook + Instagram) card.
 *
 * Mirrors GoogleCardComponent but with two structural differences:
 *
 *  - **Page-level subscription, not per-form.** Meta's webhook
 *    subscription is a per-Page POST to `/{page_id}/subscribed_apps`
 *    (Step 4). Once subscribed, EVERY Lead Form on that Page
 *    delivers to our webhook automatically. The per-form panel
 *    here is a read-only listing — we still expose per-form
 *    subscription records via `integration_subscriptions` (Step 8's
 *    field-mapping editor uses them), but the act of subscribing
 *    happens at the Page level.
 *
 *  - **Single env-level webhook URL.** Meta's webhook is configured
 *    ONCE per environment in the Meta app dashboard, not per
 *    integration. The card shows the URL for reference only — no
 *    paste-required workflow.
 *
 * Token expiry banner: Meta's long-lived user tokens last ~60 days
 * with no refresh. Shows a yellow banner when within 7 days of
 * expiry; flips to red and locks actions on `expired` status.
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
  Integration,
  IntegrationsApiService,
  IntegrationSubscription,
  MetaLeadForm,
  MetaPage,
} from './integrations-api.service';

@Component({
  selector: 'app-meta-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './meta-card.component.html',
})
export class MetaCardComponent {
  readonly integration = input<Integration | null>(null);
  readonly subscriptions = input<IntegrationSubscription[]>([]);

  readonly changed = output<void>();
  readonly inlineError = signal<string | null>(null);

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly pages = signal<MetaPage[]>([]);
  protected readonly pagesLoaded = signal(false);
  protected readonly pagesLoading = signal(false);

  /** Map page_id → forms (lazy on expansion). */
  protected readonly formsByPage = signal<Record<string, MetaLeadForm[]>>({});
  protected readonly expandedPages = signal<Set<string>>(new Set());
  protected readonly formsLoadingFor = signal<string | null>(null);

  /** In-flight Page-level subscribe/unsubscribe button. */
  protected readonly pageActionInFlight = signal<string | null>(null);

  protected readonly isConnected = computed(() => this.integration()?.status === 'connected');
  protected readonly needsReconnect = computed(() => {
    const s = this.integration()?.status;
    return s === 'expired' || s === 'error';
  });
  protected readonly webhookUrl = computed(() => this.integration()?.webhook_url ?? null);

  /** Days until token expiry — `null` when no expiry / not connected.
   *  Drives the yellow "expiring soon" banner (≤ 7 days). */
  protected readonly daysToExpiry = computed(() => {
    const exp = this.integration()?.token_expires_at;
    if (!exp) return null;
    const expiry = new Date(exp).getTime();
    if (isNaN(expiry)) return null;
    const now = Date.now();
    return Math.ceil((expiry - now) / (24 * 60 * 60 * 1000));
  });
  protected readonly tokenExpiringSoon = computed(() => {
    const d = this.daysToExpiry();
    return d !== null && d <= 7 && d >= 0;
  });

  /** Page-id → boolean: do we have ANY subscription row for any form
   *  on this page? Drives the per-Page Subscribed/Subscribe pill.
   *  (The backend's POST `/pages/{id}/subscribe` is what actually
   *  enables leadgen delivery; the per-form rows in
   *  `integration_subscriptions` are field-mapping records.) */
  protected readonly pageSubscribedMap = computed(() => {
    const id = this.integration()?.id;
    const out: Record<string, boolean> = {};
    if (!id) return out;
    const subs = this.subscriptions().filter((s) => s.integration_id === id);
    for (const page of this.pages()) {
      const forms = this.formsByPage()[page.page_id] ?? [];
      out[page.page_id] = forms.some((f) => subs.some((s) => s.external_form_id === f.form_id));
    }
    return out;
  });

  // --- actions -----------------------------------------------------

  connect(): void {
    this.inlineError.set(null);
    this.api
      .startMetaAuthorize()
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

  reconnect(): void {
    this.connect();
  }

  disconnect(): void {
    if (
      !confirm(
        'Disconnect Meta? All active Page subscriptions stop delivering leads, and you will need to re-authorise to reconnect.',
      )
    ) {
      return;
    }
    this.inlineError.set(null);
    this.api
      .disconnect('meta_ads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.pages.set([]);
          this.pagesLoaded.set(false);
          this.formsByPage.set({});
          this.expandedPages.set(new Set());
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  loadPages(): void {
    if (this.pagesLoaded() || this.pagesLoading()) return;
    if (!this.isConnected()) return;
    this.pagesLoading.set(true);
    this.api
      .listMetaPages()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.pages.set(rows);
          this.pagesLoaded.set(true);
          this.pagesLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.pagesLoading.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  togglePageExpansion(pageId: string): void {
    const next = new Set(this.expandedPages());
    if (next.has(pageId)) {
      next.delete(pageId);
      this.expandedPages.set(next);
      return;
    }
    next.add(pageId);
    this.expandedPages.set(next);
    if (this.formsByPage()[pageId]) return;
    this.formsLoadingFor.set(pageId);
    this.api
      .listMetaForms(pageId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.formsByPage.update((m) => ({ ...m, [pageId]: rows }));
          this.formsLoadingFor.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.formsLoadingFor.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  /** Page-level subscribe: POSTs to `/pages/{id}/subscribe` which
   *  hits Meta's `/subscribed_apps` endpoint + caches the Page
   *  token. Caller is expected to follow up by creating per-form
   *  subscription records (Step 8 field-mapping editor) or by
   *  leaving them out (the backend will DLQ deliveries for unknown
   *  forms, which is the right behaviour — gives the admin a chance
   *  to discover newly-added forms). */
  subscribePage(page: MetaPage): void {
    if (this.pageActionInFlight()) return;
    this.pageActionInFlight.set(page.page_id);
    this.inlineError.set(null);
    this.api
      .subscribeMetaPage(page.page_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.pageActionInFlight.set(null);
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.pageActionInFlight.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  unsubscribePage(page: MetaPage): void {
    if (this.pageActionInFlight()) return;
    if (
      !confirm(`Stop receiving leads from "${page.name}"? This also drops the cached Page token.`)
    ) {
      return;
    }
    this.pageActionInFlight.set(page.page_id);
    this.inlineError.set(null);
    this.api
      .unsubscribeMetaPage(page.page_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.pageActionInFlight.set(null);
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.pageActionInFlight.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  copyWebhookUrl(): void {
    const url = this.webhookUrl();
    if (!url) return;
    void navigator.clipboard.writeText(url).catch(() => {
      this.inlineError.set('Could not copy to clipboard.');
    });
  }
}
