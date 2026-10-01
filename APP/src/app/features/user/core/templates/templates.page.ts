import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { Subscription } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { StaffApiService, StaffListItem } from '../staff/staff-api.service';

import { ColumnFilterComponent } from '../shared/table-filters/column-filter.component';
import { ColumnFilterOption } from '../shared/table-filters/column-filter.types';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';

import { ChannelChipComponent } from './channel-chip.component';
import { TemplateStatusBadgeComponent } from './template-status-badge.component';
import {
  TemplateChannel,
  TemplateExternalStatus,
  TemplateInternalStatus,
  TemplateRead,
  TemplateSort,
  TemplatesApiService,
} from './templates-api.service';

/**
 * Templates list page — first frontend surface of the central library.
 *
 * Filters: channel + internal status + search (debounced).
 * Status badges: internal-status pill always; external-status pill only
 * when the channel has a real external review (WhatsApp / SMS-DLT).
 * "New template" button is gated on `templates.write`; junior roles
 * see read-only list with row→detail navigation only.
 *
 * Pagination is server-side (`limit` / `offset` per Step 3); page-
 * level state owns `pageIndex` + `pageSize` and computes the offset.
 */

const PAGE_SIZE = 25;
// External-status auto-refresh: silently re-fetch the list every 15s while
// any visible row is still awaiting Meta review (`pending` / `paused`).
// Terminal rows (approved / rejected / n_a) cause polling to stop — an
// idle page issues zero requests. The backend also has a 2-min celery
// sweep + webhook path; this poll bridges the gap so the operator sees
// the badge flip without hitting refresh.
const EXTERNAL_STATUS_POLL_MS = 15_000;

/** Column-filter options for the Channel <th>. Multi-select; empty
 *  selection means "no filter" (all channels). */
const CHANNEL_OPTIONS: readonly ColumnFilterOption[] = [
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'facebook', label: 'Facebook Messenger' },
  { value: 'instagram', label: 'Instagram Direct' },
  { value: 'push', label: 'Push notification' },
];

/** Column-filter options for the Status <th>. Multi-select; empty
 *  selection means "no filter" (all statuses). */
const STATUS_OPTIONS: readonly ColumnFilterOption[] = [
  { value: 'draft', label: 'Draft' },
  { value: 'in_review', label: 'In review' },
  { value: 'approved', label: 'Ready to publish' },
  { value: 'published', label: 'Published' },
  { value: 'archived', label: 'Archived' },
];

/** Channel tabs above the table (counts come from `/templates/counts`). */
const CHANNEL_TABS: ReadonlyArray<{ value: TemplateChannel; label: string }> = [
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'push', label: 'Push' },
];

const EXTERNAL_FILTER_OPTIONS: ReadonlyArray<{
  value: TemplateExternalStatus | '';
  label: string;
}> = [
  { value: '', label: 'Any Meta status' },
  { value: 'n_a', label: 'Not submitted' },
  { value: 'pending', label: 'Pending review' },
  { value: 'approved', label: 'Approved by Meta' },
  { value: 'rejected', label: 'Rejected by Meta' },
  { value: 'paused', label: 'Paused by Meta' },
];

const ACTIVE_FILTER_OPTIONS: ReadonlyArray<{ value: '' | 'active' | 'inactive'; label: string }> = [
  { value: '', label: 'Active & inactive' },
  { value: 'active', label: 'Active only' },
  { value: 'inactive', label: 'Inactive only' },
];

const SORT_OPTIONS: ReadonlyArray<{ value: TemplateSort; label: string }> = [
  { value: 'updated', label: 'Last updated' },
  { value: 'created', label: 'Newest first' },
  { value: 'name', label: 'Name A–Z' },
];

/** Internal statuses shown when "Show archived" is off and no status
 *  column filter is set — archived templates stay out of the way. */
const NON_ARCHIVED: TemplateInternalStatus[] = ['draft', 'in_review', 'approved', 'published'];

@Component({
  selector: 'app-templates-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    DatePipe,
    LucideAngularModule,
    ChannelChipComponent,
    ColumnFilterComponent,
    TemplateStatusBadgeComponent,
    MobileSelectComponent,
  ],
  templateUrl: './templates.page.html',
})
export class TemplatesPageComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly staffApi = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);

  protected readonly CHANNEL_TABS = CHANNEL_TABS;
  protected readonly EXTERNAL_FILTER_OPTIONS = EXTERNAL_FILTER_OPTIONS;
  protected readonly ACTIVE_FILTER_OPTIONS = ACTIVE_FILTER_OPTIONS;
  protected readonly SORT_OPTIONS = SORT_OPTIONS;
  protected readonly CHANNEL_OPTIONS = CHANNEL_OPTIONS;
  protected readonly STATUS_OPTIONS = STATUS_OPTIONS;
  protected readonly PAGE_SIZE = PAGE_SIZE;

  /** Attribution track — staff hydration for the "Created by" / "Approved
   *  by" columns. Loaded once at page mount; hits are cheap because the
   *  set is org-wide staff (small). Missing ids fall back to a `—` cell. */
  protected readonly staffById = signal<Map<string, StaffListItem>>(new Map());

  /** Attribution track — resolve a user id to a display name for the
   *  list cell. Returns `—` when the id is null or the staff row isn't
   *  in the hydration map (deactivated / cross-org — very rare). */
  protected staffName(userId: string | null): string {
    if (!userId) return '—';
    return this.staffById().get(userId)?.full_name ?? '—';
  }

  // List + paging state.
  protected readonly items = signal<TemplateRead[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pageIndex = signal<number>(0);

  // Filters. Column-header multi-select filters emit `string[]`; empty
  // array = no filter. The API service serializes each element as a
  // repeated query param, which FastAPI binds to `list[T] | None`.
  protected readonly channelFilter = signal<string[]>([]);
  protected readonly statusFilter = signal<string[]>([]);
  protected readonly searchQuery = signal<string>('');
  // Debounced version of `searchQuery` — what actually drives the API.
  protected readonly debouncedSearch = signal<string>('');
  protected readonly externalFilter = signal<TemplateExternalStatus | ''>('');
  protected readonly activeFilter = signal<'' | 'active' | 'inactive'>('');
  protected readonly showArchived = signal(false);
  protected readonly sort = signal<TemplateSort>('updated');
  /** Per-channel counts for the tabs (null until loaded). */
  protected readonly channelCounts = signal<Record<string, number> | null>(null);
  protected readonly channelCountTotal = computed(() =>
    Object.values(this.channelCounts() ?? {}).reduce((a, b) => a + b, 0),
  );

  // --- row actions ------------------------------------------------------
  protected readonly menuOpenFor = signal<string | null>(null);
  protected readonly confirmArchiveFor = signal<TemplateRead | null>(null);
  protected readonly rowBusy = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);

  protected readonly canWrite = computed(() => this.auth.hasPermission('templates.write'));
  /** Attribution track — reviewers see a "Needs approval" chip on rows
   *  in `in_review`. Non-reviewers can still see the underlying status
   *  badge; the chip is just an actionable nudge for people who can
   *  actually act on it. */
  protected readonly canReview = computed(() => this.auth.hasPermission('templates.review'));

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly hasPrev = computed(() => this.pageIndex() > 0);
  protected readonly hasNext = computed(() => this.pageIndex() < this.totalPages() - 1);

  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  /** In-flight list request. A newer request cancels it so a slow
   *  response for old filters can never overwrite fresher rows. */
  private listSub: Subscription | null = null;
  /** True while a user-triggered (non-silent) load is running — the
   *  background poll skips its tick instead of cancelling that load. */
  private foregroundLoading = false;

  /** True when at least one visible row is awaiting Meta review — drives
   *  the silent auto-poll. Terminal-only lists (all approved / rejected /
   *  n_a) return false and the poll stops. */
  protected readonly hasInFlightExternal = computed(() =>
    this.items().some((r) => r.external_status === 'pending' || r.external_status === 'paused'),
  );

  constructor() {
    // Re-fetch whenever any filter or pagination state changes. `effect`
    // tracks the signal reads inside the body.
    effect(() => {
      // Read every filter so the effect re-runs on change.
      const channel = this.channelFilter();
      const status = this.statusFilter();
      const q = this.debouncedSearch();
      const page = this.pageIndex();
      const external = this.externalFilter();
      const active = this.activeFilter();
      const archived = this.showArchived();
      const sort = this.sort();
      void channel;
      void status;
      void q;
      void page;
      void external;
      void active;
      void sort;
      this.reload();
      this.loadCounts(archived);
    });
    // Attribution track — one-shot staff load at page mount for the
    // "Created by" / "Approved by" cells. Failure is non-fatal; those
    // cells just show `—` and the rest of the page keeps working.
    this.staffApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const map = new Map<string, StaffListItem>();
          for (const r of rows) map.set(r.id, r);
          this.staffById.set(map);
        },
        error: () => {
          // Silent — cells degrade gracefully.
        },
      });

    // External-status auto-refresh — starts a silent 15s poll whenever a
    // pending/paused row is visible, stops when every row is terminal.
    effect(() => {
      if (this.hasInFlightExternal()) {
        this.startExternalStatusPoll();
      } else {
        this.stopExternalStatusPoll();
      }
    });

    this.destroyRef.onDestroy(() => this.stopExternalStatusPoll());
  }

  // --- filters / search -----------------------------------------------

  /** Column-header filter change handler. Both channel + status share
   *  the same signature (values: string[]) so one method keeps the
   *  bindings compact and easy to extend when a third column-filter
   *  column lands. */
  protected onColumnFilterChange(target: 'channel' | 'status', values: string[]): void {
    if (target === 'channel') this.channelFilter.set(values);
    else this.statusFilter.set(values);
    this.pageIndex.set(0);
  }

  protected onSearchInput(value: string): void {
    this.searchQuery.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.debouncedSearch.set(value.trim());
      this.pageIndex.set(0);
    }, 300);
  }

  /** Channel tab click — a single channel, or all ('' ). */
  protected selectChannelTab(channel: TemplateChannel | ''): void {
    this.channelFilter.set(channel ? [channel] : []);
    this.pageIndex.set(0);
  }

  protected activeChannelTab(): string {
    const c = this.channelFilter();
    return c.length === 1 ? c[0] : c.length === 0 ? '' : 'multi';
  }

  protected setExternalFilter(value: string): void {
    this.externalFilter.set(value as TemplateExternalStatus | '');
    this.pageIndex.set(0);
  }

  protected setActiveFilter(value: string): void {
    this.activeFilter.set(value as '' | 'active' | 'inactive');
    this.pageIndex.set(0);
  }

  protected toggleShowArchived(): void {
    this.showArchived.update((v) => !v);
    this.pageIndex.set(0);
  }

  protected setSort(value: string): void {
    this.sort.set(value as TemplateSort);
    this.pageIndex.set(0);
  }

  protected clearFilters(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.externalFilter.set('');
    this.activeFilter.set('');
    this.showArchived.set(false);
    this.channelFilter.set([]);
    this.statusFilter.set([]);
    this.searchQuery.set('');
    this.debouncedSearch.set('');
    this.pageIndex.set(0);
  }

  /** Any active filter — drives the empty-state copy + the "Clear
   *  filters" chip in the toolbar. */
  protected readonly hasActiveFilters = computed(
    () =>
      this.channelFilter().length > 0 ||
      this.statusFilter().length > 0 ||
      this.externalFilter() !== '' ||
      this.activeFilter() !== '' ||
      this.showArchived() ||
      this.debouncedSearch().length > 0,
  );

  // --- row navigation + actions -----------------------------------------

  /** Whole-row click opens the editor (links / buttons inside the row
   *  handle their own clicks). */
  protected openRow(row: TemplateRead, event: MouseEvent): void {
    if ((event.target as HTMLElement).closest('a, button')) return;
    void this.router.navigate(['/user/templates', row.id]);
  }

  protected toggleMenu(id: string, event: Event): void {
    event.stopPropagation();
    this.menuOpenFor.update((cur) => (cur === id ? null : id));
  }

  @HostListener('document:click')
  protected closeMenu(): void {
    this.menuOpenFor.set(null);
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.menuOpenFor.set(null);
    this.confirmArchiveFor.set(null);
  }

  protected duplicate(row: TemplateRead): void {
    this.menuOpenFor.set(null);
    if (this.rowBusy()) return;
    this.rowBusy.set(row.id);
    this.actionError.set(null);
    this.api
      .duplicate(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (copy) => {
          this.rowBusy.set(null);
          void this.router.navigate(['/user/templates', copy.id]);
        },
        error: (err: HttpErrorResponse) => {
          this.rowBusy.set(null);
          this.actionError.set(extractApiError(err) ?? 'Could not duplicate the template.');
        },
      });
  }

  protected askArchive(row: TemplateRead): void {
    this.menuOpenFor.set(null);
    this.confirmArchiveFor.set(row);
  }

  protected confirmArchive(): void {
    const row = this.confirmArchiveFor();
    if (!row || this.rowBusy()) return;
    this.rowBusy.set(row.id);
    this.actionError.set(null);
    this.api
      .archiveViaWorkflow(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.rowBusy.set(null);
          this.confirmArchiveFor.set(null);
          this.reload();
          this.loadCounts(this.showArchived());
        },
        error: (err: HttpErrorResponse) => {
          this.rowBusy.set(null);
          this.confirmArchiveFor.set(null);
          this.actionError.set(extractApiError(err) ?? 'Could not archive the template.');
        },
      });
  }

  private loadCounts(includeArchived: boolean): void {
    this.api
      .counts(includeArchived)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => this.channelCounts.set(c),
        // Tab counts are decoration — keep the previous numbers.
        error: () => undefined,
      });
  }

  // --- pagination -----------------------------------------------------

  protected nextPage(): void {
    if (this.hasNext()) this.pageIndex.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.hasPrev()) this.pageIndex.update((p) => p - 1);
  }

  // --- fetch ----------------------------------------------------------

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.fetchPage({ silent: false });
  }

  /** Silent fetch used by the external-status poll — no loading spinner,
   *  no error toast on transient failures (the next tick recovers). Row
   *  updates flow through the same `items` signal so OnPush + trackById
   *  only re-renders the cells whose external_status actually changed. */
  private silentReload(): void {
    this.fetchPage({ silent: true });
  }

  private fetchPage({ silent }: { silent: boolean }): void {
    if (silent && this.foregroundLoading) return;
    this.foregroundLoading = !silent;
    this.listSub?.unsubscribe();
    const offset = this.pageIndex() * PAGE_SIZE;
    const channels = this.channelFilter();
    const statuses: string[] =
      this.statusFilter().length > 0
        ? this.statusFilter()
        : this.showArchived()
          ? []
          : NON_ARCHIVED;
    const active = this.activeFilter();
    this.listSub = this.api
      .list({
        channel: channels.length > 0 ? (channels as TemplateChannel[]) : undefined,
        internal_status: statuses.length > 0 ? (statuses as TemplateInternalStatus[]) : undefined,
        external_status: this.externalFilter() || undefined,
        is_active: active === '' ? undefined : active === 'active',
        q: this.debouncedSearch() || undefined,
        sort: this.sort(),
        limit: PAGE_SIZE,
        offset,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.foregroundLoading = false;
          this.items.set(res.items);
          this.total.set(res.total);
          if (!silent) this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (silent) return;
          this.foregroundLoading = false;
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load templates.');
        },
      });
  }

  private startExternalStatusPoll(): void {
    if (this.pollTimer !== null) return;
    this.pollTimer = setInterval(() => this.silentReload(), EXTERNAL_STATUS_POLL_MS);
  }

  private stopExternalStatusPoll(): void {
    if (this.pollTimer === null) return;
    clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  // Trackby helper for the template's @for loop.
  protected trackById = (_: number, row: TemplateRead) => row.id;
}
