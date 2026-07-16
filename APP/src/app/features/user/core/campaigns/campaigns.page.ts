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
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { Campaign, CampaignStatus, CampaignsApiService } from './campaigns-api.service';
import { CreateCampaignModalComponent } from './create-campaign-modal.component';
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
    cls: 'bg-zinc-100 text-zinc-600',
    icon: '✉',
  },
  sms: { label: 'SMS', cls: 'bg-zinc-100 text-zinc-700', icon: '📱' },
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
    cls: 'bg-zinc-100 text-zinc-600 border-zinc-200',
    dot: 'text-zinc-400',
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
    cls: 'bg-rose-50 text-rose-700 border-rose-200',
    dot: 'text-rose-500',
  },
};

type StatusFilter = 'all' | CampaignStatus;
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
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<Campaign[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
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

  /** Preview filter chip row: All · Scheduled · Running · Sent · Draft · Failed. */
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
      if (status !== 'all' && c.status !== status) return false;
      if (channel !== 'all' && c.channel !== channel) return false;
      if (q && !c.name.toLowerCase().includes(q)) return false;
      return true;
    });
  });

  /** Preview stats row — 4 cards with delta strings. Per-campaign
   *  stats aren't in the list payload; real "sent this month" +
   *  rates land when the batch analytics endpoint ships (deferred
   *  from Campaigns v1). We show what we have (client-side status
   *  counts) with an honest "—" for the aggregates we can't compute
   *  yet, so the visual matches the preview without lying. */
  protected readonly stats = computed(() => {
    const rows = this.items();
    const byStatus = (s: CampaignStatus) => rows.filter((r) => r.status === s).length;
    const now = new Date();
    const thisMonth = rows.filter((r) => {
      if (!r.created_at) return false;
      const dt = new Date(r.created_at);
      return dt.getMonth() === now.getMonth() && dt.getFullYear() === now.getFullYear();
    }).length;
    return {
      thisMonth,
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
    this.api
      .list(1, 100)
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

  protected remove(c: Campaign): void {
    const ok = window.confirm(`Delete campaign "${c.name}"?`);
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

  protected onSearchInput(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
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
  protected bulkDelete(): void {
    const ids = Array.from(this.selectedIds());
    if (ids.length === 0) return;

    const rows = this.items().filter((r) => ids.includes(r.id));
    const deletable = rows.filter((r) => r.status === 'draft' || r.status === 'failed');
    const skipped = rows.length - deletable.length;

    if (deletable.length === 0) {
      window.alert(
        'None of the selected campaigns are deletable — only Draft and Failed campaigns can be removed.',
      );
      return;
    }
    const msg =
      skipped > 0
        ? `Delete ${deletable.length} campaigns? ${skipped} others will be skipped (only Draft / Failed can be deleted).`
        : `Delete ${deletable.length} campaigns?`;
    if (!window.confirm(msg)) return;

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

  protected createdByInitial(c: Campaign): string {
    if (!c.created_by_id) return 'S';
    return c.created_by_id.charAt(0).toUpperCase();
  }

  protected createdByName(c: Campaign): string {
    if (!c.created_by_id) return 'System';
    return 'User';
  }

  protected createdByBg(c: Campaign): string {
    if (!c.created_by_id) return 'bg-zinc-200 text-zinc-600';
    const idx = c.created_by_id.charCodeAt(0) % 9;
    const palette = [
      'bg-emerald-100 text-emerald-700',
      'bg-violet-100 text-violet-700',
      'bg-amber-100 text-amber-700',
      'bg-rose-100 text-rose-700',
      'bg-sky-100 text-sky-700',
      'bg-orange-100 text-orange-700',
      'bg-fuchsia-100 text-fuchsia-700',
      'bg-teal-100 text-teal-700',
      'bg-indigo-100 text-indigo-700',
    ];
    return palette[idx];
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
