import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { StaffApiService, StaffListItem } from '../staff/staff-api.service';

import { ColumnFilterComponent } from '../shared/table-filters/column-filter.component';
import { ColumnFilterOption } from '../shared/table-filters/column-filter.types';

import { ChannelChipComponent } from './channel-chip.component';
import { TemplateStatusBadgeComponent } from './template-status-badge.component';
import {
  TemplateChannel,
  TemplateInternalStatus,
  TemplateRead,
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
      void channel;
      void status;
      void q;
      void page;
      this.reload();
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

  protected clearFilters(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
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
      this.debouncedSearch().length > 0,
  );

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
    const offset = this.pageIndex() * PAGE_SIZE;
    const channels = this.channelFilter();
    const statuses = this.statusFilter();
    this.api
      .list({
        channel: channels.length > 0 ? (channels as TemplateChannel[]) : undefined,
        internal_status: statuses.length > 0 ? (statuses as TemplateInternalStatus[]) : undefined,
        q: this.debouncedSearch() || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.items.set(res.items);
          this.total.set(res.total);
          if (!silent) this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (silent) return;
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
