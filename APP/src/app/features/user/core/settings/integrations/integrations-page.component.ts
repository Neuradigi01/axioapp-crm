/**
 * Settings → Integrations page. Open to every role: the page
 * renders per-card visibility gated by two existing permission
 * keys.
 *
 *   - `settings.integrations.manage` → Google Ads, Meta Ads,
 *     WhatsApp, status/DLQ panel (Owner + Admin default).
 *   - `email.accounts.admin`         → Email (Gmail / Outlook /
 *     SMTP) sender card. Uses the `admin` key (Owner + Admin only)
 *     NOT `email.accounts.manage`, which every role holds for
 *     self-connect flows elsewhere and would leak this org-level
 *     card to Employees.
 *   - (no key)                        → Google Calendar — always
 *     visible so any user can wire their own calendar to receive
 *     appointment sync.
 *
 * The `_refresh()` API burst is skipped entirely for roles without
 * `settings.integrations.manage` (every endpoint in that fan-out
 * requires the key server-side); the calendar card fetches its own
 * status independently.
 *
 * On init: reads `?status=…&reason=…` from the URL. Google's and
 * Meta's OAuth callbacks bounce here with one of:
 *   `google_connected` / `google_denied` / `google_error`
 *   `meta_connected`   / `meta_denied`   / `meta_error`
 *   `google_calendar_connected` / `google_calendar_denied` / `google_calendar_error`
 * Shows a toast accordingly, opens the matching connector's panel
 * (so "pick the Lead Forms below" is actually below), then refetches
 * (subject to the permission gate above) so each card re-renders from
 * the new state.
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
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { FurnitureAuthService } from '../../auth/auth.service';
import { EmailHubTabComponent } from '../email/email-hub-tab.component';
import { AiProvidersCardComponent } from './ai-providers-card.component';
import { DlqListComponent } from './dlq-list.component';
// EmailSenderCardComponent is no longer rendered directly here — it
// lives on as the first sub-tab ("Sender") inside the shipped
// ``app-email-hub-tab`` (see ../email/email-hub-tab.component.ts).
// The import stays out to keep NG8113 clean.
import { RetentionCardComponent } from './retention-card.component';
import { FieldMappingEditorComponent } from './field-mapping-editor.component';
import { GoogleCalendarCardComponent } from './google-calendar-card.component';
import { GoogleCardComponent } from './google-card.component';
import { IntegrationStatusComponent } from './integration-status.component';
import { MetaCardComponent } from './meta-card.component';
import { WhatsAppCardComponent } from './whatsapp-card.component';
import { AiProvidersApiService } from './ai-providers-api.service';
import { EmailSendersApiService, isSenderOauthRevoked } from './email-senders-api.service';
import {
  Integration,
  IntegrationsApiService,
  IntegrationSubscription,
  WhatsAppStatus,
} from './integrations-api.service';

/** Rolled-up connection state shown on a summary tile. `checking`
 *  covers the moment between page load and the status call landing. */
interface TileStatus {
  status: 'connected' | 'error' | 'not_connected' | 'checking';
  label: string;
}

interface ConnectorTile {
  id: string;
  status: TileStatus['status'];
  label: string;
  type: string;
  description: string;
  /** When set, renders this letter as the icon (used for brands
   *  best identified by initials — Google's `G`, Meta's `f`). */
  letter: string | null;
  /** When `letter` is null, this lucide icon renders instead. */
  icon: string | null;
  iconBg: string;
  iconText: string;
  statusLabel: string;
  /** Button copy while not connected ("Connect", "Add key", …). */
  connectLabel: string;
}

const CHECKING: TileStatus = { status: 'checking', label: 'Checking…' };
const UNAVAILABLE: TileStatus = { status: 'not_connected', label: 'Status unavailable' };

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`;

type CallbackStatus =
  | 'google_connected'
  | 'google_denied'
  | 'google_error'
  | 'meta_connected'
  | 'meta_denied'
  | 'meta_error'
  // tasks/google-calendar-sync Step 2 callback statuses (Step 5 handler).
  | 'google_calendar_connected'
  | 'google_calendar_denied'
  | 'google_calendar_error'
  // Email sender OAuth (Gmail + Microsoft) callback statuses.
  | 'gmail_connected'
  | 'gmail_denied'
  | 'gmail_error'
  | 'microsoft_connected'
  | 'microsoft_denied'
  | 'microsoft_error';

@Component({
  selector: 'app-settings-integrations-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    GoogleCardComponent,
    GoogleCalendarCardComponent,
    MetaCardComponent,
    WhatsAppCardComponent,
    EmailHubTabComponent,
    IntegrationStatusComponent,
    DlqListComponent,
    FieldMappingEditorComponent,
    AiProvidersCardComponent,
    RetentionCardComponent,
    LucideAngularModule,
  ],
  templateUrl: './integrations-page.component.html',
})
export class IntegrationsPageComponent {
  private readonly api = inject(IntegrationsApiService);
  private readonly emailSendersApi = inject(EmailSendersApiService);
  private readonly aiProvidersApi = inject(AiProvidersApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);

  // --- per-card permission gates -----------------------------------
  //
  // The page itself is open to every role (route dropped its guard,
  // module descriptor is `always_visible`) because Google Calendar is
  // per-user and every role must be able to wire their own. The
  // org-level cards below are shown / hidden per-user based on the
  // two existing permission keys — Owner + Admin have both by default;
  // any custom role granted these keys inherits access uniformly.

  /** True when the caller may see Google Ads / Meta Ads / WhatsApp
   *  cards + the DLQ + field-mapping surfaces. */
  protected readonly canManageOrgIntegrations = computed(() =>
    this.auth.currentPermissions().includes('settings.integrations.manage'),
  );

  /** True when the caller may see the Email (Gmail / Outlook / SMTP)
   *  sender card. Gated on `email.accounts.admin` (the org-wide-view
   *  key), NOT `email.accounts.manage` — the manage key is granted to
   *  every role for a self-connect flow and would leak this org-level
   *  card to Employees. Only Owner + Admin templates hold
   *  `email.accounts.admin`; custom roles need that specific key
   *  to see this card. */
  protected readonly canManageEmailSenders = computed(() =>
    this.auth.currentPermissions().includes('email.accounts.admin'),
  );

  /** True when the caller may see the AI Providers card
   *  (tasks/ai-assistants Step 1). Billing-sensitive surface — an
   *  insider with a stored key can drain the org's OpenAI account,
   *  so Owner + Admin default; custom roles need the key explicitly. */
  protected readonly canManageAiProviders = computed(() =>
    this.auth.currentPermissions().includes('ai_providers.manage'),
  );

  /** Any org-scoped card visible → drives the empty-state banner
   *  Employees see when only the Calendar card is on the page. */
  protected readonly hasAnyOrgCard = computed(
    () =>
      this.canManageOrgIntegrations() ||
      this.canManageEmailSenders() ||
      this.canManageAiProviders(),
  );

  // --- top-level signals --------------------------------------------

  protected readonly integrations = signal<Integration[]>([]);
  protected readonly subscriptions = signal<IntegrationSubscription[]>([]);
  protected readonly whatsapp = signal<WhatsAppStatus | null>(null);
  protected readonly dlqTotal = signal<number | null>(null);
  /** First load only. Later refetches (after a card action) run in the
   *  background so open panels aren't torn down and rebuilt. */
  protected readonly loading = signal(true);
  private hasLoaded = false;
  /** First-load failure of the org-integrations fan-out. Hides only the
   *  cards that depend on that data — Calendar / Email / AI Providers
   *  fetch their own state and stay usable. */
  protected readonly loadError = signal<string | null>(null);

  /** Scroll to the open panel once the first load renders it — set
   *  when an OAuth callback auto-opens a connector. */
  private pendingPanelScroll = false;

  /** Tile statuses for the connectors whose detail cards fetch their
   *  own data (they aren't part of the org fan-out). Loaded from the
   *  same endpoints those cards call; refreshed when their panel
   *  closes so the tile reflects whatever was changed inside it. */
  protected readonly calendarTile = signal<TileStatus>(CHECKING);
  protected readonly emailTile = signal<TileStatus>(CHECKING);
  protected readonly aiTile = signal<TileStatus>(CHECKING);

  /** Inline DLQ list toggle (Step 8). Status panel emits `openDlq`
   *  on the banner click; toggles `true` and the list lazy-loads on
   *  first visibility. */
  protected readonly dlqVisible = signal(false);

  /** Active field-mapping editor target — null = closed. Set when a
   *  card emits `editMapping` with the subscription + form-field list. */
  protected readonly mappingEditor = signal<{
    subscription: IntegrationSubscription;
    formFields: string[];
    formLabel: string | null;
  } | null>(null);

  /** Bumped when the Google Calendar callback lands so the card
   *  refetches its status. The card polls-while-awaiting on its own
   *  side; this covers the case where the user clicks Connect,
   *  completes OAuth in the same tab, and returns via the redirect. */
  protected readonly calendarRefreshTick = signal(0);

  /** Which connector's detailed management card is currently open.
   *  `null` = collapsed grid only (AIXO-clean default). Set by the
   *  summary tile's Connect / Manage button; single-open so the
   *  page stays scannable. */
  protected readonly expandedConnector = signal<string | null>(null);

  // --- derived ------------------------------------------------------

  protected readonly google = computed(
    () => this.integrations().find((i) => i.provider === 'google_ads') ?? null,
  );
  protected readonly meta = computed(
    () => this.integrations().find((i) => i.provider === 'meta_ads') ?? null,
  );

  /** Summary tiles for the "Available connections" grid (AIXO
   *  pattern). Each card shows a connector's identity + a rolled-up
   *  status; the buttons scroll to the corresponding detailed card
   *  below where the actual connect / disconnect / subscribe UI
   *  lives. Kept as a computed so status pill re-renders when the
   *  underlying integration signal changes. */
  protected readonly connectors = computed<ConnectorTile[]>(() => {
    const g = this.google();
    const m = this.meta();
    const w = this.whatsapp();
    const statusFor = (
      integ: Integration | null,
    ): { status: 'connected' | 'error' | 'not_connected'; label: string } => {
      if (!integ) return { status: 'not_connected', label: 'Not connected' };
      const s = (integ.status ?? '').toLowerCase();
      if (s === 'error' || s === 'expired') return { status: 'error', label: 'Reconnect required' };
      if (s === 'active' || s === 'live' || s === 'connected')
        return { status: 'connected', label: 'Connected' };
      return { status: 'not_connected', label: 'Not connected' };
    };
    const gs = statusFor(g);
    const ms = statusFor(m);
    // Bug fix: the tile previously read `w?.connected_at` — which is a
    // historical timestamp the backend leaves populated even after
    // disconnect. Result: the tile kept showing "Connected" until the
    // row was deleted from the DB. Every other tile keys off `status`,
    // which is what disconnect actually flips to `'disconnected'`.
    const ws: { status: 'connected' | 'error' | 'not_connected'; label: string } = (() => {
      const raw = (w?.status ?? '').toLowerCase();
      if (raw === 'error' || raw === 'expired')
        return { status: 'error' as const, label: 'Reconnect required' };
      if (raw === 'connected') return { status: 'connected' as const, label: 'Connected' };
      return { status: 'not_connected' as const, label: 'Not connected' };
    })();
    // Build the tile list with per-permission gating so the summary
    // grid matches the detail cards below — Employees / custom roles
    // without the manage keys see only the Google Calendar tile.
    const tiles: ConnectorTile[] = [];
    // These three tiles read the org fan-out; when it failed to load
    // they'd show a false "Not connected", so drop them until retry.
    if (this.canManageOrgIntegrations() && !this.loadError()) {
      tiles.push(
        {
          id: 'google_ads',
          label: 'Google Ads',
          type: 'Ad platform',
          description:
            'Lead Form Extensions → CRM. New form submissions land in Leads automatically.',
          letter: 'G',
          icon: null,
          iconBg: 'bg-white',
          iconText: 'text-blue-600',
          status: gs.status,
          statusLabel: gs.label,
          connectLabel: 'Connect',
        },
        {
          id: 'meta_ads',
          label: 'Meta Ads',
          type: 'Ad platform',
          description:
            'Facebook + Instagram lead ads. Subscribe once and every Page lead flows into Leads.',
          letter: 'f',
          icon: null,
          iconBg: 'bg-blue-600',
          iconText: 'text-white',
          status: ms.status,
          statusLabel: ms.label,
          connectLabel: 'Connect',
        },
        {
          id: 'whatsapp',
          label: 'WhatsApp',
          type: 'Messaging',
          description:
            'Two-way inbox in Conversations. Send templates from Campaigns and Automations.',
          letter: null,
          icon: 'message-circle',
          iconBg: 'bg-emerald-500',
          iconText: 'text-white',
          status: ws.status,
          statusLabel: ws.label,
          connectLabel: 'Connect',
        },
      );
    }
    // Google Calendar is always shown — every role wires their own.
    tiles.push({
      id: 'google_calendar',
      label: 'Google Calendar',
      type: 'Calendar',
      description: 'Mirror appointments into each rep’s Google Calendar. Per-user connection.',
      letter: null,
      icon: 'calendar',
      iconBg: 'bg-white',
      iconText: 'text-blue-600',
      status: this.calendarTile().status,
      statusLabel: this.calendarTile().label,
      connectLabel: 'Connect',
    });
    if (this.canManageEmailSenders()) {
      tiles.push({
        id: 'email',
        label: 'Email',
        type: 'Messaging',
        description:
          'Send automation, workflow, and reply email from your Gmail / Outlook / SMTP mailbox.',
        letter: null,
        icon: 'mail',
        iconBg: 'bg-violet-500',
        iconText: 'text-white',
        status: this.emailTile().status,
        statusLabel: this.emailTile().label,
        connectLabel: 'Set up',
      });
    }
    if (this.canManageAiProviders()) {
      tiles.push({
        id: 'ai_providers',
        label: 'AI Providers',
        type: 'BYOK',
        description:
          'Bring your own OpenAI API key. Powers AI Assistants and future in-app AI features.',
        letter: null,
        icon: 'sparkles',
        iconBg: 'bg-emerald-500',
        iconText: 'text-white',
        status: this.aiTile().status,
        statusLabel: this.aiTile().label,
        connectLabel: 'Add key',
      });
    }
    return tiles;
  });

  /** The tile whose panel is open — drives the panel's title bar. */
  protected readonly expandedTile = computed(
    () => this.connectors().find((c) => c.id === this.expandedConnector()) ?? null,
  );

  /** Expand the clicked connector's detailed card (toggle: clicking
   *  the same tile again collapses it). After expand, next tick,
   *  scroll it into view so the operator lands on the flow they just
   *  chose without hunting for it on long pages. The panel being left
   *  re-reads its tile status so changes made inside it show up. */
  toggleConnector(id: string): void {
    const previous = this.expandedConnector();
    const same = previous === id;
    this.expandedConnector.set(same ? null : id);
    if (previous) this._loadTile(previous);
    if (!same) this.scrollToAnchor('connector-panel');
  }

  closeConnector(): void {
    const previous = this.expandedConnector();
    if (!previous) return;
    this.expandedConnector.set(null);
    this._loadTile(previous);
  }

  /** Tile button copy: Close while open, Reconnect on error, Manage
   *  when connected, otherwise the connector's own connect verb. */
  protected ctaFor(c: ConnectorTile): string {
    if (this.expandedConnector() === c.id) return 'Close';
    if (c.status === 'error') return 'Reconnect';
    if (c.status === 'not_connected') return c.connectLabel;
    return 'Manage';
  }

  /** Primary accent for "connect", amber for "reconnect", quiet
   *  secondary for "manage" / "close" so the grid highlights only the
   *  tiles that need action. */
  protected ctaClasses(c: ConnectorTile): string {
    if (this.expandedConnector() !== c.id) {
      if (c.status === 'error') return 'bg-amber-500 text-white hover:bg-amber-600';
      if (c.status === 'not_connected') return 'bg-accent text-white hover:brightness-95';
    }
    return 'border border-subtle bg-surface text-default hover:bg-surface-2';
  }

  /** rAF gives Angular one CD tick to render the @if block before we
   *  measure + scroll — otherwise the element doesn't exist yet. */
  private scrollToAnchor(anchor: string): void {
    requestAnimationFrame(() => {
      const el = document.getElementById(anchor);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  /** Re-run the first load after a failure (Retry button). */
  retryLoad(): void {
    this._refresh();
  }

  constructor() {
    this._readCallbackQuery();
    this._refresh();
    this._loadTile('google_calendar');
    this._loadTile('email');
    this._loadTile('ai_providers');
  }

  // --- handlers -----------------------------------------------------

  /** Called by either card after a successful Connect / Disconnect /
   *  Subscribe / Unsubscribe so the page re-fetches and every card
   *  picks up the new state in a single round trip. */
  onCardChanged(): void {
    this._refresh();
    // The Calendar card emits `changed` too; its tile isn't part of
    // the fan-out above.
    this._loadTile('google_calendar');
  }

  /** Opened from the status panel (top) or the summary card (bottom);
   *  the table renders under the summary card, so scroll it into view. */
  toggleDlq(): void {
    this.dlqVisible.update((v) => !v);
    if (this.dlqVisible()) this.scrollToAnchor('dlq-table');
  }

  /** Card emits this with the form-field list when the user clicks
   *  Edit mapping on a subscribed row. */
  openMappingEditor(
    sub: IntegrationSubscription,
    formFields: string[],
    formLabel: string | null,
  ): void {
    this.mappingEditor.set({ subscription: sub, formFields, formLabel });
  }

  closeMappingEditor(): void {
    this.mappingEditor.set(null);
  }

  onMappingSaved(): void {
    // Refetch so the next time the editor opens for the same sub it
    // reflects the saved mapping (mapping is only loaded once per
    // editor instance).
    this._refresh();
  }

  /** DLQ list emits `changed` after replay/discard so the open-DLQ
   *  count in the status panel + the bottom summary card refresh. */
  onDlqChanged(): void {
    this._refresh();
  }

  // --- internals ----------------------------------------------------

  private _refresh(): void {
    // Full-page loader only until the first successful load; after that
    // the refetch runs silently and the cards update in place.
    if (!this.hasLoaded) {
      this.loading.set(true);
      this.loadError.set(null);
    }
    // Every one of these endpoints requires `settings.integrations.manage`
    // server-side (they hydrate the Google Ads / Meta Ads / WhatsApp /
    // status-panel / DLQ cards, all of which are hidden for roles
    // without that key). Firing them for an Employee 403s and paints
    // an "Access denied" banner over a page that's otherwise valid
    // — the Google Calendar card underneath doesn't need any of it.
    // Skip the whole call cluster when the caller can't manage org
    // integrations; the calendar card fetches its own status.
    if (!this.canManageOrgIntegrations()) {
      this.integrations.set([]);
      this.subscriptions.set([]);
      this.dlqTotal.set(null);
      this.whatsapp.set(null);
      this._markLoaded();
      return;
    }
    forkJoin({
      integrations: this.api.list(),
      subscriptions: this.api.listSubscriptions(),
      dlq: this.api.listDlq({ page: 1, size: 1 }),
      whatsapp: this.api.getWhatsAppStatus(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ integrations, subscriptions, dlq, whatsapp }) => {
          this.integrations.set(integrations);
          this.subscriptions.set(subscriptions);
          this.dlqTotal.set(dlq.total);
          this.whatsapp.set(whatsapp);
          this.loadError.set(null);
          this._markLoaded();
        },
        error: (err: HttpErrorResponse) => {
          const message = extractApiError(err) ?? 'Could not load integrations.';
          if (this.hasLoaded) {
            // Background refetch failed — keep the current (slightly
            // stale) cards on screen and just tell the user.
            this.toast.error('Could not refresh integrations.', { subtitle: message });
            return;
          }
          this.loading.set(false);
          this.loadError.set(message);
        },
      });
  }

  private _markLoaded(): void {
    this.hasLoaded = true;
    this.loading.set(false);
    if (this.pendingPanelScroll) {
      this.scrollToAnchor('connector-panel');
      this.pendingPanelScroll = false;
    }
  }

  /** (Re)load the status for a self-fetching tile. No-op for tiles fed
   *  by the org fan-out, and for tiles the caller can't see. Failures
   *  degrade to "Status unavailable" — the panel itself still works. */
  private _loadTile(id: string): void {
    if (id === 'google_calendar') {
      this.api
        .getGoogleCalendarStatus()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (st) => {
            if (!st.connected) {
              this.calendarTile.set({ status: 'not_connected', label: 'Not connected' });
            } else if (st.last_error) {
              this.calendarTile.set({ status: 'error', label: 'Reconnect required' });
            } else {
              this.calendarTile.set({ status: 'connected', label: 'Connected' });
            }
          },
          error: () => this.calendarTile.set(UNAVAILABLE),
        });
    } else if (id === 'email' && this.canManageEmailSenders()) {
      this.emailSendersApi
        .list()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (rows) => {
            const live = rows.filter((r) => r.verified && !isSenderOauthRevoked(r));
            if (rows.length === 0) {
              this.emailTile.set({ status: 'not_connected', label: 'No sender yet' });
            } else if (rows.some(isSenderOauthRevoked)) {
              this.emailTile.set({ status: 'error', label: 'Reconnect required' });
            } else if (live.length > 0) {
              this.emailTile.set({ status: 'connected', label: plural(live.length, 'sender') });
            } else {
              this.emailTile.set({ status: 'error', label: 'Verification pending' });
            }
          },
          error: () => this.emailTile.set(UNAVAILABLE),
        });
    } else if (id === 'ai_providers' && this.canManageAiProviders()) {
      this.aiProvidersApi
        .list()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (keys) => {
            const live = keys.filter((k) => !k.revoked_at);
            if (live.length === 0) {
              this.aiTile.set({ status: 'not_connected', label: 'No key yet' });
            } else if (
              live.some((k) => k.test_status === 'failed') &&
              !live.some((k) => k.test_status === 'success')
            ) {
              this.aiTile.set({ status: 'error', label: 'Key test failed' });
            } else {
              this.aiTile.set({ status: 'connected', label: plural(live.length, 'key') });
            }
          },
          error: () => this.aiTile.set(UNAVAILABLE),
        });
    }
  }

  /** OAuth callback status → the connector tile whose panel holds the
   *  next step (pick forms / pages, see the new sender, …). */
  private _connectorFor(status: CallbackStatus): string {
    if (status.startsWith('google_calendar_')) return 'google_calendar';
    if (status.startsWith('google_')) return 'google_ads';
    if (status.startsWith('meta_')) return 'meta_ads';
    return 'email';
  }

  private _readCallbackQuery(): void {
    const params = this.route.snapshot.queryParamMap;
    const status = params.get('status') as CallbackStatus | null;
    if (!status) return;
    const reason = params.get('reason');
    // One notification per outcome — the standard toast used across
    // the app (previously an inline banner duplicated the same text).
    const msg = this._messageFor(status, reason);
    const subtitle = msg.detail ?? undefined;
    if (msg.kind === 'success') this.toast.success(msg.title, { subtitle });
    else if (msg.kind === 'warn') this.toast.warn(msg.title, { subtitle });
    else this.toast.error(msg.title, { subtitle });
    // Open the connector the user just came back from, and scroll to it
    // once the first load has rendered the panel.
    this.expandedConnector.set(this._connectorFor(status));
    this.pendingPanelScroll = true;
    // Bump the calendar card's refresh signal when the callback is a
    // calendar one so the card refetches its status immediately (no
    // wait for the 5s poll).
    if (status.startsWith('google_calendar_')) {
      this.calendarRefreshTick.update((v) => v + 1);
    }
    // Strip the query params so a reload doesn't re-toast. Router
    // navigation preserves the path; `queryParams: {}` + `queryParamsHandling:
    // ''` clears them.
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {},
      replaceUrl: true,
    });
  }

  private _messageFor(
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
          detail: 'Subscribe to a Page below to start receiving its Lead Ads.',
        };
      case 'google_denied':
      case 'meta_denied':
        return {
          kind: 'warn',
          title: 'Connect cancelled.',
          detail: reason ? `Reason: ${reason}` : 'Re-try the Connect button to authorise again.',
        };
      case 'google_error':
      case 'meta_error':
        return {
          kind: 'error',
          title: 'Connect failed.',
          detail: reason ? `Reason: ${reason}` : 'Try again, or check the backend logs.',
        };
      case 'google_calendar_connected':
        return {
          kind: 'success',
          title: 'Google Calendar connected.',
          detail: 'New appointments will sync to your calendar within seconds.',
        };
      case 'google_calendar_denied':
        return {
          kind: 'warn',
          title: 'Calendar connection cancelled.',
          detail: reason
            ? `Reason: ${reason}`
            : 'Re-try the Connect button on the Google Calendar card to authorise again.',
        };
      case 'google_calendar_error':
        return {
          kind: 'error',
          title: 'Calendar connect failed.',
          detail: reason ? `Reason: ${reason}` : 'Try again, or check the backend logs.',
        };
      case 'gmail_connected':
        return {
          kind: 'success',
          title: 'Gmail sender connected.',
          detail: 'It now appears on the Sender tab and is ready to send.',
        };
      case 'gmail_denied':
        return {
          kind: 'warn',
          title: 'Gmail connect cancelled.',
          detail: reason ? `Reason: ${reason}` : 'Re-try the Connect button to authorise again.',
        };
      case 'gmail_error':
        return {
          kind: 'error',
          title: 'Gmail connect failed.',
          detail: reason ? `Reason: ${reason}` : 'Try again, or check the backend logs.',
        };
      case 'microsoft_connected':
        return {
          kind: 'success',
          title: 'Microsoft sender connected.',
          detail: 'It now appears on the Sender tab and is ready to send.',
        };
      case 'microsoft_denied':
        return {
          kind: 'warn',
          title: 'Microsoft connect cancelled.',
          detail: reason ? `Reason: ${reason}` : 'Re-try the Connect button to authorise again.',
        };
      case 'microsoft_error':
        return {
          kind: 'error',
          title: 'Microsoft connect failed.',
          detail: reason ? `Reason: ${reason}` : 'Try again, or check the backend logs.',
        };
    }
  }
}
