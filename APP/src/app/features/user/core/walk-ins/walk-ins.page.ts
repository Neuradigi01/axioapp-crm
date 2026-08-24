import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

/** Backend cap on `POST /walk-ins/bulk-*` id lists. FE guards against
 *  submitting more so operators get a clean toast instead of a 422. */
const BULK_ACTION_MAX = 200;

import { FurnitureAuthService } from '../auth/auth.service';
import { ContactsApiService } from '../contacts/contacts-api.service';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { InrPipe } from '../shared/pipes/inr.pipe';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { ColumnFilterComponent } from '../shared/table-filters/column-filter.component';
import type { ColumnFilterOption } from '../shared/table-filters/column-filter.types';
import {
  QuickRegisterResponse,
  WalkIn,
  WalkInSortKey,
  WalkInStatus,
  WalkInsApiService,
  WalkInsRollup,
  SortOrder,
} from './walk-ins-api.service';
import { RegisterWalkinModalComponent } from './register-walkin-modal.component';
import {
  ConvertConfirm,
  WalkinConvertModalComponent,
} from './walkin-convert-modal/walkin-convert-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';
import { Router } from '@angular/router';

/** FE mirror of `core/walk_ins/status_workflow.ALLOWED_TRANSITIONS`. The
 * row-level action buttons read this to decide which buttons to show;
 * the backend re-enforces on every PATCH so this is purely a UX hint. */
const ALLOWED_TRANSITIONS: Record<WalkInStatus, ReadonlyArray<WalkInStatus>> = {
  browsing: ['interested', 'left'],
  interested: ['follow_up', 'converted', 'left'],
  follow_up: ['converted', 'left'],
  converted: [],
  left: ['browsing'],
};

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

type StatusFilter = 'all' | WalkInStatus;

const FILTER_CHIPS: ReadonlyArray<{ id: StatusFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'browsing', label: 'Browsing' },
  { id: 'interested', label: 'Interested' },
  { id: 'follow_up', label: 'Follow-up' },
  { id: 'converted', label: 'Converted' },
  { id: 'left', label: 'Left' },
];

class WalkInsListState extends ListPageState<WalkIn> {}

@Component({
  selector: 'app-walk-ins-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    InrPipe,
    RegisterWalkinModalComponent,
    RelativeTimePipe,
    ReactiveFormsModule,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    WalkinConvertModalComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    UrlFilterStateDirective,
    MobileSelectComponent,
    ColumnFilterComponent,
  ],
  providers: [WalkInsListState],
  templateUrl: './walk-ins.page.html',
})
export class WalkInsPageComponent {
  protected readonly initials = initials;
  protected readonly allowedTransitions = ALLOWED_TRANSITIONS;
  private readonly api = inject(WalkInsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly router = inject(Router);

  protected readonly state = inject(WalkInsListState);

  readonly statusFilter = signal<StatusFilter>('all');
  readonly chips = FILTER_CHIPS;

  readonly contactsById = signal<Record<string, ContactSummary>>({});
  readonly modalOpen = signal(false);

  /** "Open only" filter — currently-in-store visitors (time_out IS
   *  NULL). Backend already supports the `open_only=1` query param;
   *  the UI toggle here surfaces it. */
  readonly openOnly = signal(false);

  /** Pending single-row delete target (opens the shared confirm
   *  dialog). null = closed. */
  readonly pendingDelete = signal<WalkIn | null>(null);
  readonly deleteSubmitting = signal(false);
  readonly deleteError = signal<string | null>(null);

  /** Pending status-advance target. Fires from any of the row
   *  Interested / Follow-up / Left / Re-engage buttons; the confirm
   *  dialog runs the PATCH after the operator clicks through. */
  readonly pendingStatusAdvance = signal<{ walkIn: WalkIn; target: WalkInStatus } | null>(null);
  /** Pending checkout target — same rationale as status-advance. */
  readonly pendingCheckout = signal<WalkIn | null>(null);
  /** Shared submitting flag for both row-action confirms. Row-scoped
   *  progress is tracked separately by the API subscribers below. */
  readonly rowActionSubmitting = signal(false);

  /** Client-side cap on bulk selection so the operator sees a clean
   *  message instead of a 422 from the backend. */
  readonly bulkActionMax = BULK_ACTION_MAX;
  readonly overBulkCap = computed(() => this.state.selectedCount() > BULK_ACTION_MAX);

  // --- Step 2: filter + sort + scope --------------------------------------

  /** Sort dropdown. Default `time_in desc` — matches the prior server default. */
  readonly sortKey = signal<WalkInSortKey>('time_in');
  readonly sortOrder = signal<SortOrder>('desc');

  /** Date chip: `''` / `today` / `week` / `month`. Translates to a
   * `date_from` ISO timestamp the backend filters `time_in` against. */
  readonly dateChip = signal<'' | 'today' | 'week' | 'month'>('');

  /** Visibility scope: which walk-ins to show before any other filter. */
  readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());

  /** Owner filter — multi-select signal driven by the OWNER column
   *  header popover. `[]` means no filter. Held as `string[]` (not
   *  `Set`) so URL persistence can `.join(',')` round-trip cleanly
   *  and `WalkInsApiService` can serialize repeated params via
   *  `buildHttpParams`. */
  readonly assigneeFilter = signal<string[]>([]);

  /** User directory for the owner dropdown + ownerLabel lookup. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup. */
  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
  });

  /** `crm-mobile-select` shape for the Sort dropdown. Value =
   *  `${sortKey}:${sortOrder}`; `setSort` splits and drives both
   *  signals. Static list — 6 presets matching other list pages. */
  readonly sortSelectOptions: ReadonlyArray<{ value: string; label: string }> = [
    { value: 'time_in:desc', label: 'Newest visit' },
    { value: 'time_in:asc', label: 'Oldest visit' },
    { value: 'last_activity_at:desc', label: 'Recent activity' },
    { value: 'last_activity_at:asc', label: 'Stale (oldest activity)' },
    { value: 'created_at:desc', label: 'Newest created' },
    { value: 'created_at:asc', label: 'Oldest created' },
  ];

  /** Owner options for the OWNER column popover — every active org
   *  user, with the current user pinned first as "Me" so the previous
   *  "quick-filter to my rows" affordance stays one click away. */
  readonly assigneeOptions = computed<ColumnFilterOption[]>(() => {
    const me = this.auth.currentUserId();
    const rows = this.users();
    const out: ColumnFilterOption[] = [];
    if (me) {
      const meUser = rows.find((u) => u.id === me);
      out.push({ value: me, label: meUser ? `Me (${meUser.full_name})` : 'Me' });
    }
    for (const u of rows) {
      if (u.id === me) continue;
      out.push({ value: u.id, label: u.full_name });
    }
    return out;
  });

  /** Whether the scope toggle should be visible. Junior staff get the
   * implicit "mine" default with no toggle. */
  readonly canChangeScope = computed(() => {
    const role = this.auth.currentRoleName().toLowerCase();
    return role === 'owner' || role === 'admin' || role.includes('manager');
  });

  /** Items as fetched from the server — server already sorts + filters. */
  readonly visible = computed<WalkIn[]>(() => this.state.items());

  // --- Step 3: selection + bulk + single reassign + convert ---------------

  /** Single-row reassign (from the pencil — added in Step 3 as a future
   * polish on row hover). Same component as bulk. */
  readonly singleReassignWalkIn = signal<WalkIn | null>(null);
  readonly singleReassignSubmitting = signal(false);
  readonly singleReassignError = signal<string | null>(null);

  /** Convert-to-lead modal state. */
  readonly convertWalkIn = signal<WalkIn | null>(null);
  readonly convertSubmitting = signal(false);
  readonly convertError = signal<string | null>(null);

  /** Can the user run the Convert action? Same permission as creating
   * a lead, which is what the convert side-effect produces. */
  readonly canConvert = computed(() => this.auth.hasPermission('leads.write'));

  /** Can the user reassign a walk-in? Owner pencil + bulk reassign
   * both gate on this. Junior staff lack the key. */
  readonly canReassign = computed(() => this.auth.hasPermission('walkins.reassign'));

  /** URL ↔ state map for filters + view state. */
  readonly urlState: UrlFilterStateConfig = {
    status: {
      read: () => this.statusFilter(),
      write: (v) => {
        if (
          v === 'all' ||
          v === 'browsing' ||
          v === 'interested' ||
          v === 'follow_up' ||
          v === 'converted' ||
          v === 'left'
        ) {
          this.statusFilter.set(v);
        }
      },
      queryKey: 'status',
      defaultValue: 'all',
    },
    assignee: {
      // Comma-separated on the URL (`?assignee=<uuid>,<uuid>`) so the
      // shape stays a single string per key — matches contacts and
      // keeps shared URLs compact.
      read: () => this.assigneeFilter().join(','),
      write: (v) => this.assigneeFilter.set(this.parseCsvFilter(v)),
      queryKey: 'assignee',
    },
    date_chip: {
      read: () => this.dateChip(),
      write: (v) => {
        if (v === '' || v === 'today' || v === 'week' || v === 'month') {
          this.dateChip.set(v);
        }
      },
      queryKey: 'date_chip',
    },
    scope: {
      read: () => this.scope(),
      write: (v) => {
        if (v === 'mine' || v === 'team' || v === 'all') this.scope.set(v);
      },
      queryKey: 'scope',
    },
    sort: {
      read: () => this.sortKey(),
      write: (v) => {
        if (v === 'time_in' || v === 'created_at' || v === 'last_activity_at') {
          this.sortKey.set(v);
        }
      },
      queryKey: 'sort',
      defaultValue: 'time_in',
    },
    order: {
      read: () => this.sortOrder(),
      write: (v) => {
        if (v === 'asc' || v === 'desc') this.sortOrder.set(v);
      },
      queryKey: 'order',
      defaultValue: 'desc',
    },
    open_only: {
      read: () => (this.openOnly() ? '1' : ''),
      write: (v) => this.openOnly.set(v === '1' || v === 'true'),
      queryKey: 'open_only',
    },
  };

  // --- KPI cards ---
  //
  // W7 — Server-side roll-up. Replaces the previous client-side
  // computation that only summed the loaded page (broken at
  // multi-location scale). Values pull from `GET /walk-ins/rollup`
  // and are refreshed after any mutation (register / checkout /
  // delete / convert / bulk actions).

  readonly rollup = signal<WalkInsRollup | null>(null);
  readonly todayCount = computed(() => this.rollup()?.today_count ?? 0);
  readonly convertedTodayCount = computed(() => this.rollup()?.today_converted ?? 0);
  readonly interestedOrFollowUpCount = computed(() => this.rollup()?.interested_or_follow_up ?? 0);
  readonly conversionRate = computed(() => {
    const pct = this.rollup()?.conversion_rate_pct;
    return pct == null ? null : Math.round(pct);
  });
  readonly avgVisitDuration = computed<number | null>(() => {
    const m = this.rollup()?.avg_duration_min;
    return m == null ? null : Math.round(m);
  });
  /** W9 — average wait time (queue → engagement) over last 30d. */
  readonly avgWaitMin = computed<number | null>(() => {
    const m = this.rollup()?.avg_wait_min;
    return m == null ? null : Math.round(m);
  });

  constructor() {
    this.state.bulkActions.set([
      {
        key: 'reassign',
        label: 'Reassign to…',
        icon: 'user-cog',
        permissionKey: 'walkins.reassign',
      },
      { key: 'checkout', label: 'Check out', icon: 'log-out', permissionKey: 'walkins.write' },
      {
        key: 'delete',
        label: 'Delete',
        icon: 'trash-2',
        danger: true,
        permissionKey: 'walkins.write',
      },
    ]);
    this.reload();
    this.reloadRollup();
    effect(() => {
      // Fetch missing contact summaries whenever the visible list changes.
      const ids = new Set(this.state.items().map((w) => w.contact_id));
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });
  }

  /** OWNER column popover callback — write the new selection and
   *  refetch. Mirrors the contacts page pattern. */
  protected onOwnerFilterChange(values: string[]): void {
    this.assigneeFilter.set(values);
    this.reload();
  }

  /** Parse a comma-separated URL filter value into a de-duped
   *  `string[]`. Symmetric with `read: () => filter.join(',')`. */
  private parseCsvFilter(raw: string): string[] {
    if (!raw) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const part of raw.split(',')) {
      const trimmed = part.trim();
      if (!trimmed || seen.has(trimmed)) continue;
      seen.add(trimmed);
      out.push(trimmed);
    }
    return out;
  }

  protected setFilter(f: StatusFilter): void {
    this.statusFilter.set(f);
    this.reload();
  }

  protected setDateChip(value: string): void {
    if (value !== '' && value !== 'today' && value !== 'week' && value !== 'month') {
      return;
    }
    this.dateChip.set(value);
    this.reload();
  }

  protected setScope(value: string): void {
    if (value !== 'mine' && value !== 'team' && value !== 'all') return;
    this.scope.set(value);
    // Scope is applied via `resolveAssignee()` on reload — 'mine'
    // collapses to the caller uuid; 'team' / 'all' clear the
    // assignee override (server-side row-visibility handles the rest).
    this.reload();
  }

  protected toggleOpenOnly(): void {
    this.openOnly.update((v) => !v);
    this.reload();
  }

  protected setSort(value: string): void {
    const [key, order] = value.split(':');
    if (key !== 'time_in' && key !== 'created_at' && key !== 'last_activity_at') {
      return;
    }
    if (order !== 'asc' && order !== 'desc') return;
    this.sortKey.set(key);
    this.sortOrder.set(order);
    this.reload();
  }

  /** Default visibility based on role. Same heuristic as leads.page. */
  private defaultScopeForRole(): 'mine' | 'team' | 'all' {
    const role = this.auth.currentRoleName();
    if (!role) return 'mine';
    const r = role.toLowerCase();
    if (r === 'owner' || r === 'admin') return 'all';
    if (r.includes('manager')) return 'team';
    return 'mine';
  }

  /** Resolve the owner filter to a UUID array for the API call.
   *
   * Priority order:
   *   1. OWNER column-header popover picks always win — sent as-is.
   *   2. Scope toggle: 'mine' collapses to `[caller uuid]` when no
   *      column picks are active.
   *   3. 'team' / 'all' clear the filter — backend row-visibility
   *      (list_walk_ins_visible_to) still gates non-privileged
   *      callers to their own book.
   */
  private resolveAssignee(): string[] | undefined {
    const raw = this.assigneeFilter();
    if (raw.length > 0) return raw;
    if (this.scope() === 'mine') {
      const me = this.auth.currentUserId();
      return me ? [me] : undefined;
    }
    return undefined;
  }

  /** Date chip → ISO `date_from` cutoff. Returns null when no chip set. */
  private resolveDateFrom(): string | null {
    const chip = this.dateChip();
    if (!chip) return null;
    const now = new Date();
    if (chip === 'today') {
      now.setHours(0, 0, 0, 0);
    } else if (chip === 'week') {
      // Last 7 days rolling window — captures Monday-Sunday for typical
      // store hours regardless of which weekday it is.
      now.setDate(now.getDate() - 7);
    } else if (chip === 'month') {
      now.setDate(now.getDate() - 30);
    }
    return now.toISOString();
  }

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  // --- Selection + bulk ---------------------------------------------------

  protected toggleRow(id: string, event: Event): void {
    event.stopPropagation();
    this.state.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected isSelected(id: string): boolean {
    return this.state.selectedIds().has(id);
  }

  protected clearSelection(): void {
    this.state.selectedIds.set(new Set());
  }

  protected onBulkAction(key: string): void {
    this.state.bulkError.set(null);
    if (this.state.selectedCount() > BULK_ACTION_MAX) {
      this.state.bulkError.set(
        `Too many rows selected (${this.state.selectedCount()}). ` +
          `The server caps bulk actions at ${BULK_ACTION_MAX}. ` +
          `Narrow your selection and try again.`,
      );
      return;
    }
    if (key === 'reassign') this.state.bulkModal.set('reassign');
    else if (key === 'checkout') this.state.bulkModal.set('checkout');
    else if (key === 'delete') this.state.bulkModal.set('delete');
  }

  protected closeBulkModal(): void {
    this.state.bulkModal.set(null);
    this.state.bulkSubmitting.set(false);
    this.state.bulkError.set(null);
  }

  protected onBulkReassign(payload: ReassignConfirm): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.state.bulkSubmitting.set(false);
          // Surface the split so an operator selecting 20 rows and
          // reassigning to a user who already owns 5 of them sees the
          // honest "15 reassigned, 5 already owned this seat" summary
          // instead of a misleading "20 reassigned".
          if (result.already_assigned > 0) {
            this.state.loadError.set(
              `Reassigned ${result.reassigned}. ` +
                `${result.already_assigned} already owned this seat.`,
            );
          }
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not reassign.');
        },
      });
  }

  protected onBulkCheckout(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkCheckout(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not check out.');
        },
      });
  }

  protected onBulkDelete(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    // W1 — single-call bulk-delete (mirror of leads). Previously fired
    // N sequential DELETEs; now one round-trip + one audit entry.
    this.api
      .bulkDelete(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not delete walk-ins.');
        },
      });
  }

  /** W2 — single-row delete triggered from the row action button.
   *  Opens the shared `<app-confirm-dialog>` (same UX as bulk-delete)
   *  instead of `window.confirm` so the danger action reads consistently
   *  and errors surface inline rather than in the page-level banner. */
  protected onDeleteRow(w: WalkIn): void {
    this.deleteError.set(null);
    this.pendingDelete.set(w);
  }

  protected cancelDelete(): void {
    this.pendingDelete.set(null);
    this.deleteSubmitting.set(false);
    this.deleteError.set(null);
  }

  protected confirmDelete(): void {
    const target = this.pendingDelete();
    if (!target) return;
    this.deleteSubmitting.set(true);
    this.deleteError.set(null);
    this.api
      .delete(target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteSubmitting.set(false);
          this.state.items.update((rows) => rows.filter((r) => r.id !== target.id));
          this.pendingDelete.set(null);
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.deleteSubmitting.set(false);
          this.deleteError.set(extractApiError(err) ?? 'Could not delete walk-in.');
        },
      });
  }

  // --- Single reassign (pencil — wired but no row UI yet, reachable
  // programmatically; the dedicated pencil button can be added later
  // without backend changes). ----------------------------------------------

  protected openSingleReassign(walkIn: WalkIn): void {
    this.singleReassignError.set(null);
    this.singleReassignWalkIn.set(walkIn);
  }

  protected closeSingleReassign(): void {
    this.singleReassignWalkIn.set(null);
    this.singleReassignSubmitting.set(false);
    this.singleReassignError.set(null);
  }

  protected onSingleReassign(payload: ReassignConfirm): void {
    const w = this.singleReassignWalkIn();
    if (!w) return;
    this.singleReassignSubmitting.set(true);
    this.singleReassignError.set(null);
    this.api
      .reassign(w.id, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.singleReassignSubmitting.set(false);
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.closeSingleReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.singleReassignSubmitting.set(false);
          this.singleReassignError.set(extractApiError(err) ?? 'Could not reassign walk-in.');
        },
      });
  }

  // --- Convert-to-lead ----------------------------------------------------

  protected openConvert(walkIn: WalkIn): void {
    this.convertError.set(null);
    this.convertWalkIn.set(walkIn);
  }

  protected closeConvert(): void {
    this.convertWalkIn.set(null);
    this.convertSubmitting.set(false);
    this.convertError.set(null);
  }

  protected onConvertConfirm(payload: ConvertConfirm): void {
    const w = this.convertWalkIn();
    if (!w) return;
    this.convertSubmitting.set(true);
    this.convertError.set(null);
    this.api
      .convert(w.id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.convertSubmitting.set(false);
          // Update the local row's linked_lead_id so the "→ Lead" badge
          // appears immediately.
          this.state.items.update((rows) =>
            rows.map((r) =>
              r.id === resp.walk_in_id ? { ...r, linked_lead_id: resp.lead_id } : r,
            ),
          );
          this.reloadRollup();
          this.closeConvert();
          // Send the user straight to the new lead detail page so
          // they can fill in the details. Previously navigated to the
          // list page with `?q=<uuid>` which relied on the search box
          // matching a UUID substring — fragile and inconsistent.
          this.router.navigate(['/user/leads', resp.lead_id]);
        },
        error: (err: HttpErrorResponse) => {
          this.convertSubmitting.set(false);
          this.convertError.set(extractApiError(err) ?? 'Could not convert walk-in.');
        },
      });
  }

  /** Advance a walk-in to a new state. Optimistic — patches the
   *  single row on success, and on error reverts ONLY that row
   *  (surgical) so concurrent mutations to sibling rows during the
   *  in-flight request aren't blown away by a wholesale rollback. */
  /** Row-button click → open confirm dialog. The PATCH fires from
   *  `confirmAdvanceStatus` once the operator clicks through. */
  protected advanceStatus(walkIn: WalkIn, target: WalkInStatus): void {
    if (this.rowActionSubmitting()) return;
    this.pendingStatusAdvance.set({ walkIn, target });
  }

  protected closeAdvanceStatus(): void {
    this.pendingStatusAdvance.set(null);
  }

  protected confirmAdvanceStatus(): void {
    const pending = this.pendingStatusAdvance();
    if (!pending) return;
    if (this.rowActionSubmitting()) return;
    const { walkIn, target } = pending;
    this.rowActionSubmitting.set(true);
    const beforeRow = { ...walkIn };
    this.state.items.update((rows) =>
      rows.map((w) => (w.id === walkIn.id ? { ...w, status: target } : w)),
    );
    this.api
      .update(walkIn.id, { status: target })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.rowActionSubmitting.set(false);
          this.pendingStatusAdvance.set(null);
          this.state.items.update((rows) => rows.map((w) => (w.id === updated.id ? updated : w)));
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.rowActionSubmitting.set(false);
          this.pendingStatusAdvance.set(null);
          this.state.items.update((rows) =>
            rows.map((w) => (w.id === beforeRow.id ? beforeRow : w)),
          );
          this.state.loadError.set(extractApiError(err) ?? 'Could not update walk-in status.');
        },
      });
  }

  /** Human label for the status-advance confirm dialog title / body.
   *  Mirrors the button labels in the row action strip. */
  protected labelForStatus(target: WalkInStatus): string {
    switch (target) {
      case 'interested':
        return 'Interested';
      case 'follow_up':
        return 'Follow-up';
      case 'converted':
        return 'Converted';
      case 'left':
        return 'Left';
      case 'browsing':
        return 'Re-engage';
    }
  }

  protected openRegister(): void {
    this.modalOpen.set(true);
  }

  protected closeRegister(): void {
    this.modalOpen.set(false);
  }

  protected onRegistered(_event: QuickRegisterResponse): void {
    this.modalOpen.set(false);
    this.reload();
    this.reloadRollup();
  }

  /** Row-button click → open confirm dialog. The POST fires from
   *  `confirmCheckout` once the operator clicks through. */
  protected onCheckout(walkIn: WalkIn): void {
    if (this.rowActionSubmitting()) return;
    this.pendingCheckout.set(walkIn);
  }

  protected closeCheckout(): void {
    this.pendingCheckout.set(null);
  }

  protected confirmCheckout(): void {
    const walkIn = this.pendingCheckout();
    if (!walkIn) return;
    if (this.rowActionSubmitting()) return;
    this.rowActionSubmitting.set(true);
    // Optimistic: stamp time_out locally to a near-now ISO so the
    // duration column populates immediately. Replaced by server value.
    // Surgical per-row revert on error (see `confirmAdvanceStatus`).
    const optimisticNow = new Date().toISOString();
    const beforeRow = { ...walkIn };
    this.state.items.update((rows) =>
      rows.map((w) => (w.id === walkIn.id ? { ...w, time_out: optimisticNow } : w)),
    );
    this.api
      .checkout(walkIn.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.rowActionSubmitting.set(false);
          this.pendingCheckout.set(null);
          this.state.items.update((rows) => rows.map((w) => (w.id === updated.id ? updated : w)));
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.rowActionSubmitting.set(false);
          this.pendingCheckout.set(null);
          this.state.items.update((rows) =>
            rows.map((w) => (w.id === beforeRow.id ? beforeRow : w)),
          );
          this.state.loadError.set(extractApiError(err) ?? 'Could not check out walk-in.');
        },
      });
  }

  protected statusClass(status: WalkInStatus): string {
    switch (status) {
      case 'browsing':
        return 'bg-surface-2 text-default border-subtle';
      case 'interested':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'follow_up':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'converted':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'left':
        return 'bg-red-100 text-red-700 ring-red-200';
    }
  }

  protected contactFor(id: string): ContactSummary | null {
    return this.contactsById()[id] ?? null;
  }

  protected formatTime(iso: string | null): string {
    if (iso === null) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected formatDate(iso: string | null): string {
    if (iso === null) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
  protected formatDuration(min: string | null): string {
    if (min === null) return '—';
    const n = Number(min);
    if (!Number.isFinite(n)) return '—';
    if (n < 1) return `${Math.round(n * 60)}s`;
    if (n < 60) return `${Math.round(n)} min`;
    const hours = Math.floor(n / 60);
    const rem = Math.round(n % 60);
    return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
  }

  private reload(): void {
    this.state.loading.set(true);
    this.state.loadError.set(null);
    const filter = this.statusFilter();
    this.api
      .list({
        status: filter === 'all' ? undefined : filter,
        assigned_to: this.resolveAssignee(),
        open_only: this.openOnly() || undefined,
        date_from: this.resolveDateFrom() ?? undefined,
        sort: this.sortKey(),
        order: this.sortOrder(),
        size: 100,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.state.items.set(rows);
          this.state.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set([]);
          this.state.loading.set(false);
          this.state.loadError.set(extractApiError(err) ?? 'Could not load walk-ins.');
        },
      });
  }

  private reloadRollup(): void {
    this.api
      .rollup()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => this.rollup.set(r),
        // Header KPIs are aesthetic — silently hide on failure so a
        // roll-up error never blocks the main list view.
        error: () => this.rollup.set(null),
      });
  }

  /** W5 — schedule a follow-up appointment from a walk-in row.
   *  Deep-links to the appointments page with the contact prefilled
   *  so the operator lands directly on the book-appointment modal. */
  protected onScheduleAppointment(w: WalkIn): void {
    this.router.navigate(['/user/appointments'], {
      queryParams: {
        new: 1,
        contact_id: w.contact_id,
        assigned_to_id: w.assigned_to_id ?? undefined,
      },
    });
  }

  private fetchContacts(ids: string[]): void {
    // Single batched POST replaces the previous per-id fan-out (up to
    // 100 round-trips for a fully-loaded page). Backend caps id lists
    // at 200 which matches the list page-size; chunk here in case a
    // future page-size ever exceeds it.
    const CHUNK = 200;
    for (let i = 0; i < ids.length; i += CHUNK) {
      const slice = ids.slice(i, i + CHUNK);
      this.contactsApi
        .hydrateByIds(slice)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (rows) => {
            this.contactsById.update((cache) => {
              const next = { ...cache };
              for (const c of rows) {
                next[c.id] = { id: c.id, full_name: c.full_name, phone: c.phone };
              }
              return next;
            });
          },
          // Silent: contact summaries are decorative; the list still
          // renders id-only if the hydrate hiccups.
          error: () => undefined,
        });
    }
  }

  private isToday(iso: string): boolean {
    const d = new Date(iso);
    const now = new Date();
    return (
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    );
  }
}
