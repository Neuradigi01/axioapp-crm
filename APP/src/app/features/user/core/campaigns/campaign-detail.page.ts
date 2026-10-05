import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '@shared/components/toast/toast.service';
import { finalize } from 'rxjs/operators';

import { FurnitureAuthService } from '../auth/auth.service';

import { CampaignAnalyticsTabComponent } from './detail/analytics-tab.component';
import {
  Campaign,
  CampaignMessage,
  CampaignMessageStatus,
  CampaignStats,
  CampaignsApiService,
} from './campaigns-api.service';
import { ContactsApiService } from '../contacts/contacts-api.service';

const POLL_INTERVAL_MS = 5_000;
/** A scheduled campaign further out than this isn't polled — nothing
 *  can change until it starts (the first tick after that picks it up). */
const POLL_SCHEDULE_HORIZON_MS = 5 * 60_000;

/** Step 21 — campaign-detail page tabs. "Overview" is the existing
 *  stats + messages view; "Analytics" mounts the new funnel +
 *  failure-breakdown widget. */
export type CampaignDetailTab = 'overview' | 'analytics';

/**
 * Campaign detail — stats KPIs + per-message table with retry.
 *
 * Polls stats + messages every 5s while the campaign is `scheduled`
 * or `running` so the operator sees the dispatch progress without
 * refreshing. Polling stops once status flips to `done` / `failed`.
 */
@Component({
  selector: 'app-campaign-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, CampaignAnalyticsTabComponent],
  templateUrl: './campaign-detail.page.html',
})
export class CampaignDetailPageComponent {
  /** Step 21 — active sub-tab. Defaults to the existing overview. */
  protected readonly activeTab = signal<CampaignDetailTab>('overview');

  protected setTab(tab: CampaignDetailTab): void {
    this.activeTab.set(tab);
  }

  private readonly api = inject(CampaignsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(FurnitureAuthService);

  /** The Analytics endpoints need `whatsapp.analytics.read`; without it
   *  the tab only rendered error boxes, so it's hidden instead. */
  protected readonly canViewAnalytics = this.auth.hasPermission('whatsapp.analytics.read');

  /** Requests still in flight from the last refresh — a poll tick is
   *  skipped while > 0 so slow responses can't stack up or land out of
   *  order. */
  private inFlight = 0;

  protected readonly id: string = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly campaign = signal<Campaign | null>(null);
  protected readonly stats = signal<CampaignStats | null>(null);
  protected readonly messages = signal<CampaignMessage[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly retryingId = signal<string | null>(null);

  /** contact_id → {full_name, phone, email} lookup. Populated after
   *  each `listMessages()` refresh via a batched `/contacts/hydrate`
   *  round-trip so the Messages table shows real names instead of
   *  8-char id snippets. */
  protected readonly contactsById = signal<
    Record<string, { full_name: string; phone: string | null; email: string | null }>
  >({});

  /** Campaigns v1 Step 05 — funnel branches on channel. Email
   *  campaigns render Opened / Clicked / Bounced boxes; WA campaigns
   *  keep the existing Read box. */
  protected readonly isEmailCampaign = computed(() => this.campaign()?.channel === 'email');

  protected readonly statusBadge = computed(() => {
    const c = this.campaign();
    if (!c) return null;
    const map: Record<string, { label: string; cls: string }> = {
      draft: { label: 'Draft', cls: 'bg-surface-2 text-default ring-subtle' },
      scheduled: { label: 'Scheduled', cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
      running: { label: 'Running', cls: 'bg-sky-50 text-sky-700 ring-sky-200' },
      done: { label: 'Done', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
      failed: { label: 'Failed', cls: 'bg-red-500/10 text-red-400 ring-red-500/20' },
    };
    return map[c.status];
  });

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    if (!this.id) {
      this.loadError.set('No campaign id in URL.');
      return;
    }
    this.loadAll();
    // Tear the poll down on destroy — DestroyRef → cleanup callback.
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected loadAll(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(this.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.campaign.set(c);
          this.maybeStartPolling();
        },
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load campaign.'),
      });
    this.refreshStatsAndMessages();
  }

  protected refreshStatsAndMessages(): void {
    this.inFlight = 2;
    const settle = (): void => {
      this.inFlight = Math.max(0, this.inFlight - 1);
    };
    this.api
      .stats(this.id)
      .pipe(finalize(settle), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.stats.set(s);
          // Keep the header badge in step with the dispatch (it was
          // fetched once, so it stayed "Running" after the send ended).
          this.campaign.update((c) =>
            c && c.status !== s.status ? { ...c, status: s.status } : c,
          );
          // Stop polling if the campaign reached a terminal state.
          if (s.status === 'done' || s.status === 'failed') {
            this.stopPolling();
          }
        },
        error: () => {
          /* keep last stats */
        },
      });
    this.api
      .listMessages(this.id)
      .pipe(finalize(settle), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.messages.set(rows);
          this.loading.set(false);
          // A later successful refresh clears an earlier failed one.
          if (this.campaign()) this.loadError.set(null);
          this._hydrateContactsForMessages(rows);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load messages.');
        },
      });
  }

  /** Batched `POST /contacts/hydrate` — fetches names/phones/emails
   *  for every contact referenced by the messages table so we can
   *  render real names instead of 8-char id snippets. Skips any id
   *  already cached. */
  private _hydrateContactsForMessages(rows: CampaignMessage[]): void {
    const cache = this.contactsById();
    const missing = [...new Set(rows.map((r) => r.contact_id))].filter((id) => !cache[id]);
    if (missing.length === 0) return;
    this.contactsApi
      .hydrateByIds(missing)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (contacts) => {
          this.contactsById.update((prev) => {
            const next = { ...prev };
            for (const c of contacts) {
              next[c.id] = {
                full_name: c.full_name,
                phone: c.phone,
                email: c.email,
              };
            }
            return next;
          });
        },
        error: () => {
          // Silent — the table falls back to the id-snippet shortId()
          // if hydration fails.
        },
      });
  }

  /** Real name for a contact, or a fallback to the id-snippet if we
   *  haven't hydrated it yet (or hydration failed). */
  protected contactLabel(contactId: string): string {
    return this.contactsById()[contactId]?.full_name ?? this.shortId(contactId);
  }

  /** Secondary line (phone or email) for a hydrated contact — the
   *  Messages table uses it as a subtitle so the operator can identify
   *  a customer without leaving the page. */
  protected contactSubtitle(contactId: string): string | null {
    const c = this.contactsById()[contactId];
    if (!c) return null;
    return c.phone ?? c.email ?? null;
  }

  protected retry(msg: CampaignMessage): void {
    this.retryingId.set(msg.id);
    this.api
      .retry(this.id, msg.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.retryingId.set(null);
          this.refreshStatsAndMessages();
        },
        error: (err: HttpErrorResponse) => {
          this.retryingId.set(null);
          this.toast.error('Retry failed', { subtitle: extractApiError(err) ?? undefined });
        },
      });
  }

  /** Step 3.5.13 — delivery rate as a percentage of the sent count.
   *  Returns null when nothing has been sent yet (avoids "0% of 0"
   *  noise during the first dispatch tick). */
  protected readonly deliveryRate = computed<number | null>(() => {
    const s = this.stats();
    if (!s) return null;
    const sent = s.sent + s.delivered + s.read;
    if (sent === 0) return null;
    return Math.round(((s.delivered + s.read) / sent) * 100);
  });

  /** Read rate as a percentage of delivered (read-after-delivered). */
  protected readonly readRate = computed<number | null>(() => {
    const s = this.stats();
    if (!s) return null;
    const delivered = s.delivered + s.read;
    if (delivered === 0) return null;
    return Math.round((s.read / delivered) * 100);
  });

  /** Failure rate as a percentage of total attempts (sent + failed).
   *  Excludes still-queued rows to avoid alarming the operator while
   *  dispatch is in progress. */
  protected readonly failureRate = computed<number | null>(() => {
    const s = this.stats();
    if (!s) return null;
    const attempted = s.sent + s.delivered + s.read + s.failed;
    if (attempted === 0) return null;
    return Math.round((s.failed / attempted) * 100);
  });

  /** Step 3.5.13 — WhatsApp-style tick for the per-row table.
   *
   *   `read`      → ✓✓ blue   — Meta `status='read'`
   *   `delivered` → ✓✓ grey   — Meta `status='delivered'`
   *   `sent`      → ✓ grey    — outbound POST succeeded
   *   `pending`   → clock     — queued, not yet attempted
   *   `failed`    → x         — terminal failure
   */
  protected tickState(m: CampaignMessage): 'read' | 'delivered' | 'sent' | 'pending' | 'failed' {
    if (m.status === 'failed') return 'failed';
    if (m.read_at) return 'read';
    if (m.delivered_at) return 'delivered';
    if (m.sent_at) return 'sent';
    return 'pending';
  }

  protected messageStatusCls(s: CampaignMessageStatus): string {
    switch (s) {
      case 'sent':
      case 'delivered':
      case 'read':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      // Campaigns v1 Step 05 — Email tracking states share the WA
      // "read" palette because both mean "recipient engaged".
      case 'opened':
      case 'clicked':
        return 'bg-violet-50 text-violet-700 ring-violet-200';
      case 'queued':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      case 'failed':
        return 'bg-red-500/10 text-red-400 ring-red-500/20';
    }
  }

  protected messageStatusLabel(s: CampaignMessageStatus): string {
    const labels: Record<CampaignMessageStatus, string> = {
      queued: 'Queued',
      sent: 'Sent',
      delivered: 'Delivered',
      read: 'Read',
      opened: 'Opened',
      clicked: 'Clicked',
      failed: 'Failed',
    };
    return labels[s] ?? s;
  }

  protected channelLabel(channel: string): string {
    if (channel === 'whatsapp') return 'WhatsApp';
    if (channel === 'email') return 'Email';
    return channel.charAt(0).toUpperCase() + channel.slice(1);
  }

  /** Empty-messages copy that matches where the campaign actually is. */
  protected emptyMessagesText(): string {
    switch (this.campaign()?.status) {
      case 'scheduled':
        return 'Nothing sent yet — this campaign sends automatically at its scheduled time.';
      case 'running':
        return 'Sending has started — messages appear here as they go out.';
      case 'draft':
        return "This is a draft — start it from the Campaigns list when you're ready.";
      default:
        return 'No messages were recorded for this campaign.';
    }
  }

  protected formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  protected shortId(id: string): string {
    return id.slice(0, 8);
  }

  private maybeStartPolling(): void {
    const c = this.campaign();
    if (!c) return;
    if (c.status === 'scheduled' || c.status === 'running') {
      if (this.pollTimer !== null) return;
      this.pollTimer = setInterval(() => this.pollTick(), POLL_INTERVAL_MS);
    } else {
      this.stopPolling();
    }
  }

  /** One poll: skipped while the previous refresh is still in flight,
   *  while the tab is hidden, and for a campaign scheduled well into
   *  the future. */
  private pollTick(): void {
    if (this.inFlight > 0 || document.hidden) return;
    const c = this.campaign();
    if (c?.status === 'scheduled' && c.schedule_at) {
      const until = new Date(c.schedule_at).getTime() - Date.now();
      if (until > POLL_SCHEDULE_HORIZON_MS) return;
    }
    this.refreshStatsAndMessages();
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}
