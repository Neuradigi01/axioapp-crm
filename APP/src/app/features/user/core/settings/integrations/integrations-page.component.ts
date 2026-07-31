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
import { DlqListComponent } from './dlq-list.component';
import { EmailSenderCardComponent } from './email-sender-card.component';
import { FieldMappingEditorComponent } from './field-mapping-editor.component';
import { GoogleCalendarCardComponent } from './google-calendar-card.component';
import { GoogleCardComponent } from './google-card.component';
import { IntegrationStatusComponent } from './integration-status.component';
import { MetaCardComponent } from './meta-card.component';
import { WhatsAppCardComponent } from './whatsapp-card.component';
import {
  Integration,
  IntegrationsApiService,
  IntegrationSubscription,
  WhatsAppStatus,
} from './integrations-api.service';

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
  | 'google_calendar_error';

@Component({
  selector: 'app-settings-integrations-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    GoogleCardComponent,
    GoogleCalendarCardComponent,
    MetaCardComponent,
    WhatsAppCardComponent,
    EmailSenderCardComponent,
    IntegrationStatusComponent,
    DlqListComponent,
    FieldMappingEditorComponent,
    LucideAngularModule,
  ],
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
  protected readonly whatsapp = signal<WhatsAppStatus | null>(null);
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
  protected readonly connectors = computed<
    Array<{
      id: string;
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
      status: 'connected' | 'error' | 'not_connected';
      statusLabel: string;
      anchor: string;
    }>
  >(() => {
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
    const ws: { status: 'connected' | 'error' | 'not_connected'; label: string } = w?.connected_at
      ? { status: 'connected', label: 'Connected' }
      : { status: 'not_connected', label: 'Not connected' };
    return [
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
        anchor: 'card-google-ads',
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
        anchor: 'card-meta-ads',
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
        anchor: 'card-whatsapp',
      },
      {
        id: 'google_calendar',
        label: 'Google Calendar',
        type: 'Calendar',
        description: 'Mirror appointments into each rep’s Google Calendar. Per-user connection.',
        letter: null,
        icon: 'calendar',
        iconBg: 'bg-white',
        iconText: 'text-blue-600',
        status: 'not_connected',
        statusLabel: 'Per-user',
        anchor: 'card-google-calendar',
      },
      {
        id: 'email',
        label: 'Email',
        type: 'Messaging',
        description:
          'Send automation, workflow, and reply email from your Gmail / Outlook / SMTP mailbox.',
        letter: null,
        icon: 'mail',
        iconBg: 'bg-violet-500',
        iconText: 'text-white',
        status: 'not_connected',
        statusLabel: 'Manage below',
        anchor: 'card-email-sender',
      },
    ];
  });

  /** Expand the clicked connector's detailed card (toggle: clicking
   *  the same tile again collapses it). After expand, next tick,
   *  scroll it into view so the operator lands on the flow they just
   *  chose without hunting for it on long pages. */
  toggleConnector(id: string, anchor: string): void {
    const same = this.expandedConnector() === id;
    this.expandedConnector.set(same ? null : id);
    if (!same) {
      // rAF gives Angular one CD tick to render the @if block before we
      // measure + scroll — otherwise the element doesn't exist yet.
      requestAnimationFrame(() => {
        const el = document.getElementById(anchor);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }

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

  toggleDlq(): void {
    this.dlqVisible.update((v) => !v);
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
    this.loading.set(true);
    this.loadError.set(null);
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
    // Bump the calendar card's refresh signal when the callback is a
    // calendar one so the card refetches its status immediately (no
    // wait for the 5s poll).
    if (status.startsWith('google_calendar_')) {
      this.calendarRefreshTick.update((v) => v + 1);
    }
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
    }
  }
}
