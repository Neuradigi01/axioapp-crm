import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../environments/environment';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import {
  Campaign,
  CampaignDashboardStats,
  CampaignStatus,
  CampaignsApiService,
} from './campaigns-api.service';
import { CreateCampaignModalComponent } from './create-campaign-modal.component';

/** Minimal shape returned by `GET /users` — enough to resolve
 *  `created_by_id` → display name for the Created By column. */
interface OrgUser {
  id: string;
  full_name: string;
  is_active: boolean;
}
import { extractApiError } from '@core/services/api-error.util';

interface ChannelStyle {
  label: string;
  cls: string;
  icon: string;
}

/**
 * Campaigns v1 — table view mirroring
 * ``tasks/campaigns-page-update/preview.html`` Screen 1 pixel-for-pixel.
 *
 * Scope locked to WhatsApp + Email (memory
 * ``project_campaigns_scope.md``). Legacy rows on SMS / FB / IG / Web
 * still render safely because the CHANNEL_STYLES map has fallbacks —
 * the filter dropdown just doesn't offer them.
 */
// Colour palette pulled straight from preview.html's ``.channel-icon.wa``
// (#DCFCE7 / #16A34A) and ``.channel-icon.em`` (#F4F4F5 / #52525B) so the
// icon squares render byte-identical between mockup and the live app.
const CHANNEL_STYLES: Record<string, ChannelStyle> = {
  whatsapp: {
    label: 'WhatsApp',
    cls: 'bg-emerald-50 text-emerald-600',
    icon: '💬',
  },
  email: {
    label: 'Email',
    cls: 'bg-surface-2 text-muted',
    icon: '✉',
  },
  sms: { label: 'SMS', cls: 'bg-surface-2 text-default', icon: '📱' },
  facebook: { label: 'Facebook', cls: 'bg-blue-100 text-blue-700', icon: 'f' },
  instagram: {
    label: 'Instagram',
    cls: 'bg-fuchsia-100 text-fuchsia-700',
    icon: '📸',
  },
  web: { label: 'Web', cls: 'bg-sky-100 text-sky-700', icon: '🌐' },
};

/** Status pill palettes match preview Screen 1's ``.chip`` variants. */
const STATUS_STYLES: Record<CampaignStatus, { label: string; cls: string; dot: string }> = {
  draft: {
    label: 'Draft',
    cls: 'bg-surface-2 text-muted border-subtle',
    dot: 'text-faint',
  },
  scheduled: {
    label: 'Scheduled',
    cls: 'bg-amber-50 text-amber-700 border-amber-200',
    dot: 'text-amber-500',
  },
  running: {
    label: 'Running',
    cls: 'bg-violet-50 text-violet-700 border-violet-200',
    dot: 'text-violet-500',
  },
  // Preview labels ``done`` rows as "Sent" in the filter chip row +
  // the row pill — a campaign that finished dispatching IS sent. We
  // honour the preview's user-facing language but keep the underlying
  // ``done`` status value so the rest of the app doesn't shift.
  done: {
    label: 'Sent',
    cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    dot: 'text-emerald-500',
  },
  failed: {
    label: 'Failed',
    cls: 'bg-red-500/10 text-red-400 border-red-500/20',
    dot: 'text-red-500',
  },
};

/** ``'archived'`` is a virtual filter — not a real backend status.
 *  When active it triggers a re-fetch with ``archived_only=true`` so
 *  the operator can review historical (soft-archived) campaigns.
 *  Every other value maps 1:1 to a ``CampaignStatus``. */
type StatusFilter = 'all' | 'archived' | CampaignStatus;
type ChannelFilter = 'all' | 'whatsapp' | 'email';

@Component({
  selector: 'app-campaigns-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink, CreateCampaignModalComponent],
  templateUrl: './campaigns.page.html',
})
export class CampaignsPageComponent {
  private readonly api = inject(CampaignsApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly confirmDialog = inject(ConfirmDialogService);

  protected readonly items = signal<Campaign[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  /** Aggregated this-month KPIs powering the top cards. `null` until
   *  the first fetch resolves; failure keeps it `null` so the cards
   *  render "—" without swallowing the list load. */
  protected readonly dashboardStats = signal<CampaignDashboardStats | null>(null);

  /** Org users, loaded once on init and used to resolve
   *  `created_by_id` → real full name in the Created By column.
   *  Fetch failure just leaves the map empty — the column falls back
   *  to a truncated id so the row still renders. */
  private readonly users = signal<OrgUser[]>([]);
  private readonly usersById = computed<Map<string, OrgUser>>(() => {
    const map = new Map<string, OrgUser>();
    for (const u of this.users()) map.set(u.id, u);
    return map;
  });
  protected readonly modalOpen = signal(false);
  protected readonly busyId = signal<string | null>(null);

  /** IDs of campaigns the operator has ticked in the row checkboxes.
   *  Header checkbox toggles the intersection with ``filteredItems``
   *  so "select all" respects the active filters (which is what
   *  every mail-merge / bulk-action UX does). */
  protected readonly selectedIds = signal<ReadonlySet<string>>(new Set());
  protected readonly bulkBusy = signal(false);

  // --- filter + search state ---------------------------------------

  protected readonly statusFilter = signal<StatusFilter>('all');
  protected readonly channelFilter = signal<ChannelFilter>('all');
  protected readonly search = signal<string>('');
  protected readonly channelMenuOpen = signal(false);

  /** Preview filter chip row: All · Scheduled · Running · Sent · Draft · Failed · Archived. */
  protected readonly statusChips: ReadonlyArray<{
    value: StatusFilter;
    label: string;
  }> = [
    { value: 'all', label: 'All' },
    { value: 'scheduled', label: 'Scheduled' },
    { value: 'running', label: 'Running' },
    // "Sent" is the preview's public label for finished campaigns.
    { value: 'done', label: 'Sent' },
    { value: 'draft', label: 'Draft' },
    { value: 'failed', label: 'Failed' },
    // Soft-archived rows — hidden from every other chip; picking this
    // triggers a re-fetch scoped to ``archived_only=true``.
    { value: 'archived', label: 'Archived' },
  ];

  protected readonly channelOptions: ReadonlyArray<{
    value: ChannelFilter;
    label: string;
  }> = [
    { value: 'all', label: 'All channels' },
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'email', label: 'Email' },
  ];

  protected readonly filteredItems = computed<Campaign[]>(() => {
    const status = this.statusFilter();
    const channel = this.channelFilter();
    const q = this.search().trim().toLowerCase();
    return this.items().filter((c) => {
      // The Archived chip fetches an archived-only slice via
      // ``reload()``; the client-side predicate here just passes them
      // all through. Every other filter still applies (channel, q).
      if (status !== 'all' && status !== 'archived' && c.status !== status) return false;
      if (channel !== 'all' && c.channel !== channel) return false;
      if (q && !c.name.toLowerCase().includes(q)) return false;
      return true;
    });
  });

  /** Preview stats row — 3 cards. `thisMonth` is the count of
   *  messages actually SENT this month (from the aggregated dashboard
   *  endpoint), not campaigns created — the label used to mislead
   *  before the endpoint shipped. `deliveryRate` / `readRate` are
   *  formatted percentages or "—" when the denominator is zero. */
  protected readonly stats = computed(() => {
    const rows = this.items();
    const byStatus = (s: CampaignStatus) => rows.filter((r) => r.status === s).length;
    const ds = this.dashboardStats();
    const pct = (r: number | null | undefined): string =>
      r === null || r === undefined ? '—' : `${Math.round(r * 100)}%`;
    return {
      thisMonth: ds?.sent ?? 0,
      deliveryRate: pct(ds?.delivery_rate),
      readRate: pct(ds?.read_rate),
      running: byStatus('running'),
      scheduled: byStatus('scheduled'),
      sent: byStatus('done'),
      draft: byStatus('draft'),
      failed: byStatus('failed'),
      total: rows.length,
    };
  });

  protected readonly channelFilterLabel = computed(() => {
    const opt = this.channelOptions.find((o) => o.value === this.channelFilter());
    return opt?.label ?? 'All channels';
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    // The Archived chip is a virtual filter — the backend keeps
    // soft-archived rows out of the default response, so we swap in
    // ``archived_only=true`` when the operator picks it.
    const archivedOnly = this.statusFilter() === 'archived';
    this.api
      .list(1, 100, archivedOnly ? { archived_only: true } : {})
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          // Purge any selected ids that vanished — a race between the
          // list refresh and a background dispatch could otherwise
          // leave the bulk-actions bar counting phantom rows.
          const alive = new Set(resp.items.map((r) => r.id));
          this.selectedIds.update((set) => {
            const next = new Set<string>();
            for (const id of set) if (alive.has(id)) next.add(id);
            return next;
          });
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load campaigns.');
        },
      });
    // Dashboard KPIs load independently — a failed aggregation must
    // not block the list, and vice versa. The cards fall back to "—"
    // when the fetch fails.
    this.api
      .dashboardStats()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => this.dashboardStats.set(s),
        error: () => this.dashboardStats.set(null),
      });
    // Org users for the Created By column. Independent of the list
    // load; a `/users` failure just leaves names unresolved (the
    // helpers fall back to a shortened id).
    this.http
      .get<OrgUser[]>(`${environment.apiBaseUrl}/users`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.users.set(rows),
        error: () => this.users.set([]),
      });
  }

  protected openModal(): void {
    this.modalOpen.set(true);
  }

  protected onCreated(campaign: Campaign): void {
    this.modalOpen.set(false);
    this.items.update((rows) => [campaign, ...rows]);
  }

  protected onCancel(): void {
    this.modalOpen.set(false);
  }

  protected start(c: Campaign): void {
    // Campaigns v1 Step 07c — run the readiness pre-flight before
    // firing the actual start. Non-empty ``blockers`` means the backend
    // ``enqueue`` will 400 anyway; surface the first blocker as a clear
    // banner + link the user at Store Profile / Sender Setup rather
    // than dumping the raw 400 detail on them.
    this.busyId.set(c.id);
    this.loadError.set(null);
    this.api
      .readiness(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (readiness) => {
          if (readiness.blockers.length > 0) {
            this.busyId.set(null);
            this.loadError.set(readiness.blockers[0].message);
            return;
          }
          this.api
            .start(c.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: () => {
                this.busyId.set(null);
                this.reload();
              },
              error: (err: HttpErrorResponse) => {
                this.busyId.set(null);
                this.loadError.set(extractApiError(err) ?? 'Could not start campaign.');
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not check readiness.');
        },
      });
  }

  protected async remove(c: Campaign): Promise<void> {
    // Pre-check the backend's deletability rule client-side so
    // non-deletable statuses (scheduled / running / done) surface a
    // clear info dialog instead of eating a 409 from the API. Archived
    // rows escape this gate — once the operator has hidden a campaign
    // they can also drop it (and its cascading message receipts).
    if (!c.archived_at && c.status !== 'draft' && c.status !== 'failed') {
      await this.confirmDialog.ask({
        title: `${this._statusLabel(c.status)} campaigns can't be deleted`,
        body:
          `"${c.name}" is ${this._statusLabel(c.status).toLowerCase()}, so it's part of your send history. ` +
          `Only Draft and Failed campaigns can be removed outright — deleting a Sent, Scheduled, or ` +
          `Running campaign would orphan the per-message delivery, open, and click receipts your ` +
          `reporting relies on. Archive it first (the row is hidden from the default list and its ` +
          `sender stops blocking teardown); you can then permanently delete it from the Archived filter.`,
        confirmLabel: 'Got it',
        hideCancel: true,
      });
      return;
    }
    // Archived-row delete carries a heavier warning: message receipts
    // cascade with the row (FK ON DELETE CASCADE), so per-campaign
    // metrics disappear from reporting for good.
    const archivedBody =
      `"${c.name}" and every per-message receipt tied to it — delivery, open, click, and ` +
      `unsubscribe history — are removed permanently. This cannot be undone.`;
    const ok = await this.confirmDialog.ask({
      title: `Delete campaign "${c.name}"?`,
      body: c.archived_at ? archivedBody : 'The campaign row is removed. This cannot be undone.',
      confirmLabel: 'Delete',
      cancelLabel: 'Keep it',
      danger: true,
    });
    if (!ok) return;
    this.busyId.set(c.id);
    this.api
      .delete(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyId.set(null);
          this.items.update((rows) => rows.filter((r) => r.id !== c.id));
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not delete campaign.');
        },
      });
  }

  /** Soft-archive an eligible campaign. Draft / Sent / Failed rows can
   *  be archived — the row is hidden from the default list but every
   *  ``tbl_campaign_messages`` receipt (delivery, open, click history)
   *  stays intact, so per-campaign reporting still resolves. Archiving
   *  also drops the row from the "sender in use" pre-check, which is
   *  the only way to tear down an SMTP sender whose only outstanding
   *  reference is a long-since-completed campaign. */
  protected async archive(c: Campaign): Promise<void> {
    if (c.archived_at) return;
    const ok = await this.confirmDialog.ask({
      title: `Archive campaign "${c.name}"?`,
      body:
        `The campaign is hidden from the default list. Every per-message metric row (delivery, ` +
        `open, click history) is preserved, and any sender it referenced stops blocking deletion. ` +
        `You can unarchive it later from the Archived filter.`,
      confirmLabel: 'Archive',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    this.busyId.set(c.id);
    this.api
      .archive(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busyId.set(null);
          // If we're on the default view, drop the row from the visible
          // list. If we're on the Archived view, patch it in place so
          // the ``archived_at`` timestamp reflects the update.
          if (this.statusFilter() === 'archived') {
            this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          } else {
            this.items.update((rows) => rows.filter((r) => r.id !== updated.id));
          }
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not archive campaign.');
        },
      });
  }

  /** Restore an archived campaign back to the default list. Idempotent
   *  server-side; a no-op archived_at reset is treated as success. */
  protected async unarchive(c: Campaign): Promise<void> {
    if (!c.archived_at) return;
    const ok = await this.confirmDialog.ask({
      title: `Unarchive "${c.name}"?`,
      body: 'The campaign returns to the default list at its original status.',
      confirmLabel: 'Unarchive',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    this.busyId.set(c.id);
    this.api
      .unarchive(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busyId.set(null);
          if (this.statusFilter() === 'archived') {
            // Row no longer matches the archived-only slice — drop it.
            this.items.update((rows) => rows.filter((r) => r.id !== updated.id));
          } else {
            this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          }
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not unarchive campaign.');
        },
      });
  }

  /** Pick a status chip. Crossing the archived/not-archived boundary
   *  triggers a re-fetch since the backend keeps soft-archived rows
   *  out of the default list — the ``archived_only=true`` slice is a
   *  separate query. Same-side transitions stay client-side. */
  protected setStatusFilter(value: StatusFilter): void {
    const prev = this.statusFilter();
    if (prev === value) return;
    this.statusFilter.set(value);
    const crossesArchived = prev === 'archived' || value === 'archived';
    if (crossesArchived) this.reload();
  }

  /** True when the campaign can be archived. Scheduled / Running rows
   *  need to finish (or be cancelled) first — archiving mid-dispatch
   *  would leave the dispatcher chasing a hidden row. */
  protected canArchive(c: Campaign): boolean {
    if (c.archived_at) return false;
    return c.status === 'draft' || c.status === 'done' || c.status === 'failed';
  }

  /** Human label for a ``CampaignStatus`` value — matches the filter
   *  chip row (``done`` → "Sent") so error messaging reads consistent
   *  with what the operator sees on-screen. */
  private _statusLabel(status: CampaignStatus): string {
    switch (status) {
      case 'draft':
        return 'Draft';
      case 'scheduled':
        return 'Scheduled';
      case 'running':
        return 'Running';
      case 'done':
        return 'Sent';
      case 'failed':
        return 'Failed';
    }
  }

  protected onSearchInput(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  /** Export the currently visible (filter- + search-aware) campaign
   *  list as a CSV. Columns mirror the on-screen table so the download
   *  matches what the operator picked; per-row send/delivered/read
   *  counts aren't in the list payload and would require N+1 stats
   *  calls, so they're deliberately omitted from the v1 export. */
  protected downloadCsv(): void {
    const rows = this.filteredItems();
    if (rows.length === 0) {
      this.loadError.set('Nothing to export — the current filter matches no campaigns.');
      return;
    }
    const header = [
      'Name',
      'Channel',
      'Template',
      'Audience',
      'Status',
      'Scheduled',
      'Created by',
      'Created at',
    ];
    const escape = (v: string): string => {
      // RFC 4180 — wrap in quotes if the value contains a comma, quote,
      // or newline, and double any internal quotes.
      if (/[",\r\n]/.test(v)) return `"${v.replace(/"/g, '""')}"`;
      return v;
    };
    const body = rows.map((c) =>
      [
        c.name,
        this.channelStyle(c.channel).label,
        this.templatePreview(c),
        this.audiencePreview(c),
        this.statusStyle(c.status).label,
        this.formatSchedule(c.schedule_at, c.status),
        this.createdByName(c),
        this.relativeDate(c.created_at),
      ]
        .map(escape)
        .join(','),
    );
    // Prepend BOM so Excel opens UTF-8 correctly on Windows (otherwise
    // accented chars in campaign names render as mojibake).
    const csv = '﻿' + [header.join(','), ...body].join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const today = new Date();
    const stamp =
      `${today.getFullYear()}-` +
      `${String(today.getMonth() + 1).padStart(2, '0')}-` +
      `${String(today.getDate()).padStart(2, '0')}`;
    const link = document.createElement('a');
    link.href = url;
    link.download = `campaigns-${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  // --- Selection ---------------------------------------------------

  protected isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  /** True when every currently-visible (filtered) row is selected —
   *  drives the header checkbox's ``checked`` state. Returns false
   *  when there are no rows so the header doesn't render as ticked
   *  on an empty list. */
  protected readonly allVisibleSelected = computed<boolean>(() => {
    const visible = this.filteredItems();
    if (visible.length === 0) return false;
    const sel = this.selectedIds();
    return visible.every((r) => sel.has(r.id));
  });

  /** True when SOME (not all) visible rows are selected — drives the
   *  header checkbox's indeterminate visual (the small "—" fill). */
  protected readonly someVisibleSelected = computed<boolean>(() => {
    const visible = this.filteredItems();
    if (visible.length === 0) return false;
    const sel = this.selectedIds();
    const count = visible.filter((r) => sel.has(r.id)).length;
    return count > 0 && count < visible.length;
  });

  protected selectedCount = computed<number>(() => this.selectedIds().size);

  protected toggleRow(id: string): void {
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** Header checkbox — flips the whole filtered set. Rows outside the
   *  current filter are left untouched so switching filters keeps the
   *  operator's earlier picks. */
  protected toggleAll(): void {
    const visible = this.filteredItems();
    const allSelected = this.allVisibleSelected();
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (allSelected) {
        for (const r of visible) next.delete(r.id);
      } else {
        for (const r of visible) next.add(r.id);
      }
      return next;
    });
  }

  protected clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  /** Bulk-delete confirmed selection. Only rows in a mutable state
   *  (draft / failed) are actually deletable — the rest surface a
   *  "N could not be deleted" summary at the end so the operator
   *  knows why the number in the pill doesn't match the outcome. */
  protected async bulkDelete(): Promise<void> {
    const ids = Array.from(this.selectedIds());
    if (ids.length === 0) return;

    const rows = this.items().filter((r) => ids.includes(r.id));
    // Archived rows can also be dropped — the operator has already
    // hidden them and accepted "gone from the default list". Draft /
    // Failed remain in-scope regardless.
    const deletable = rows.filter(
      (r) => r.archived_at || r.status === 'draft' || r.status === 'failed',
    );
    const skipped = rows.length - deletable.length;

    if (deletable.length === 0) {
      await this.confirmDialog.ask({
        title: 'No campaigns can be deleted',
        body:
          `Only Draft, Failed, or already-Archived campaigns can be removed — deleting a live Sent, ` +
          `Scheduled, or Running campaign would orphan the per-message delivery, open, and click ` +
          `receipts your reporting relies on. Archive them first (the Archive action stays on the ` +
          `row and unblocks any sender they were pinning), then delete from the Archived filter.`,
        confirmLabel: 'Got it',
        hideCancel: true,
      });
      return;
    }
    const bulkTitle = `Delete ${deletable.length} campaign${deletable.length === 1 ? '' : 's'}?`;
    const hasArchived = deletable.some((r) => r.archived_at);
    const permanentSuffix = hasArchived
      ? ' Archived rows drop their per-message metrics as well.'
      : '';
    const bulkBody =
      skipped > 0
        ? `${skipped} of the ${rows.length} selected can't be removed (only Draft, Failed, or Archived are deletable) and will be skipped. This cannot be undone.${permanentSuffix}`
        : `The selected campaign rows are removed. This cannot be undone.${permanentSuffix}`;
    const ok = await this.confirmDialog.ask({
      title: bulkTitle,
      body: bulkBody,
      confirmLabel: `Delete ${deletable.length}`,
      cancelLabel: 'Cancel',
      danger: true,
    });
    if (!ok) return;

    this.bulkBusy.set(true);
    let remaining = deletable.length;
    let failed = 0;
    for (const row of deletable) {
      this.api
        .delete(row.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.items.update((items) => items.filter((i) => i.id !== row.id));
            this.selectedIds.update((set) => {
              const next = new Set(set);
              next.delete(row.id);
              return next;
            });
            remaining -= 1;
            if (remaining === 0) {
              this.bulkBusy.set(false);
              if (failed > 0) {
                this.loadError.set(`${failed} campaign(s) could not be deleted.`);
              }
            }
          },
          error: () => {
            failed += 1;
            remaining -= 1;
            if (remaining === 0) {
              this.bulkBusy.set(false);
              if (failed > 0) {
                this.loadError.set(`${failed} campaign(s) could not be deleted.`);
              }
            }
          },
        });
    }
  }

  protected pickChannel(value: ChannelFilter): void {
    this.channelFilter.set(value);
    this.channelMenuOpen.set(false);
  }

  protected toggleChannelMenu(): void {
    this.channelMenuOpen.update((v) => !v);
  }

  protected channelStyle(channel: string): ChannelStyle {
    return CHANNEL_STYLES[channel] ?? CHANNEL_STYLES['web'];
  }

  protected statusStyle(s: CampaignStatus): {
    label: string;
    cls: string;
    dot: string;
  } {
    return STATUS_STYLES[s];
  }

  protected audiencePreview(c: Campaign): string {
    if (c.audience_filter?.group_id) return 'Saved group';
    const parts: string[] = [];
    if (c.audience_filter?.q) parts.push(`"${c.audience_filter.q}"`);
    if (c.audience_filter?.source) parts.push(`source: ${c.audience_filter.source}`);
    if (c.audience_filter?.tag) parts.push(`tag: ${c.audience_filter.tag}`);
    return parts.length ? parts.join(' · ') : 'Everyone';
  }

  protected templatePreview(c: Campaign): string {
    if (c.template_id) return 'From template library';
    if (c.template) {
      const trimmed = c.template.replace(/\s+/g, ' ').trim();
      return trimmed.length > 60 ? trimmed.slice(0, 57) + '…' : trimmed;
    }
    if (c.body_html) return 'HTML body';
    return '—';
  }

  protected formatSchedule(iso: string | null, status: CampaignStatus): string {
    if (status === 'running') return 'Now (running)';
    if (!iso) return status === 'draft' ? '—' : 'Immediate';
    const dt = new Date(iso);
    return (
      dt.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
      ', ' +
      dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    );
  }

  protected relativeDate(iso: string | null): string {
    if (!iso) return '—';
    const dt = new Date(iso);
    return dt.toLocaleDateString([], {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  protected createdByName(c: Campaign): string {
    if (!c.created_by_id) return 'System';
    const hit = this.usersById().get(c.created_by_id);
    // Fall back to a shortened id when `/users` hasn't loaded yet or
    // the campaign was created by a user no longer in the org — better
    // than mislabelling every row "User".
    return hit?.full_name || c.created_by_id.slice(0, 8) + '…';
  }

  protected createdByInitial(c: Campaign): string {
    if (!c.created_by_id) return 'S';
    const name = this.usersById().get(c.created_by_id)?.full_name;
    if (name) {
      // First letter of first + last word — matches how avatar
      // fallbacks render elsewhere in the app (e.g. contacts list).
      const parts = name.trim().split(/\s+/);
      const first = parts[0]?.[0] ?? '';
      const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
      return (first + last).toUpperCase() || '?';
    }
    return c.created_by_id.charAt(0).toUpperCase();
  }

  protected createdByBg(c: Campaign): string {
    if (!c.created_by_id) return 'bg-surface-2 text-muted';
    const palette = [
      'bg-emerald-100 text-emerald-700',
      'bg-violet-100 text-violet-700',
      'bg-amber-100 text-amber-700',
      'bg-red-500/10 text-red-400',
      'bg-sky-100 text-sky-700',
      'bg-orange-100 text-orange-700',
      'bg-fuchsia-100 text-fuchsia-700',
      'bg-teal-100 text-teal-700',
      'bg-indigo-100 text-indigo-700',
    ];
    // Hash the id so the same user always gets the same colour tile
    // regardless of load order.
    let hash = 0;
    for (const ch of c.created_by_id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return palette[hash % palette.length];
  }

  protected clearFilters(): void {
    this.statusFilter.set('all');
    this.channelFilter.set('all');
    this.search.set('');
  }

  protected hasActiveFilters(): boolean {
    return (
      this.statusFilter() !== 'all' ||
      this.channelFilter() !== 'all' ||
      this.search().trim().length > 0
    );
  }
}
