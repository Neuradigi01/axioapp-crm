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
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError, distinctUntilChanged } from 'rxjs/operators';

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
import { InrPipe } from '../shared/pipes/inr.pipe';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import {
  QuickRegisterResponse,
  WalkIn,
  WalkInSortKey,
  WalkInStatus,
  WalkInsApiService,
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

  // --- Step 2: filter + sort + scope --------------------------------------

  /** Sort dropdown. Default `time_in desc` — matches the prior server default. */
  readonly sortKey = signal<WalkInSortKey>('time_in');
  readonly sortOrder = signal<SortOrder>('desc');

  /** Date chip: `''` / `today` / `week` / `month`. Translates to a
   * `date_from` ISO timestamp the backend filters `time_in` against. */
  readonly dateChip = signal<'' | 'today' | 'week' | 'month'>('');

  /** Visibility scope: which walk-ins to show before any other filter. */
  readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());

  /** Owner picker: empty / 'me' / UUID. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** User directory for the owner dropdown + ownerLabel lookup. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup. */
  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
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
      read: () => this.assigneeControl.value,
      write: (v) => this.assigneeControl.setValue(v),
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
  };

  // --- KPI cards (computed from `all`) ---

  readonly todayCount = computed(
    () => this.state.items().filter((w) => this.isToday(w.time_in)).length,
  );
  readonly convertedTodayCount = computed(
    () =>
      this.state.items().filter((w) => w.status === 'converted' && this.isToday(w.updated_at))
        .length,
  );
  /** Combined "warm leads" count â€” interested + follow_up across all loaded rows. */
  readonly interestedOrFollowUpCount = computed(
    () =>
      this.state.items().filter((w) => w.status === 'interested' || w.status === 'follow_up')
        .length,
  );
  readonly conversionRate = computed(() => {
    const today = this.todayCount();
    if (today === 0) return null;
    const converted = this.convertedTodayCount();
    return Math.round((converted / today) * 100);
  });
  /** Average visit duration in minutes, across all checked-out walk-ins. */
  readonly avgVisitDuration = computed<number | null>(() => {
    const completed = this.state
      .items()
      .map((w) => (w.duration_min !== null ? Number(w.duration_min) : null))
      .filter((n): n is number => n !== null && Number.isFinite(n));
    if (completed.length === 0) return null;
    const total = completed.reduce((a, b) => a + b, 0);
    return Math.round(total / completed.length);
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
    effect(() => {
      // Fetch missing contact summaries whenever the visible list changes.
      const ids = new Set(this.state.items().map((w) => w.contact_id));
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });

    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
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

  /** Resolve the assignee filter to a UUID for the API call.
   * `''` → undefined; `'me'` → current user; UUID → that UUID. */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    return raw;
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
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
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
    // walk_ins has no batched delete endpoint — call per row. v2: add one.
    let done = 0;
    let failed = 0;
    const finish = () => {
      this.state.bulkSubmitting.set(false);
      this.clearSelection();
      this.closeBulkModal();
      if (failed > 0) {
        this.state.loadError.set(`${failed} delete(s) failed; ${done} succeeded.`);
      }
      this.reload();
    };
    for (const id of ids) {
      this.api
        .delete(id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            done++;
            if (done + failed === ids.length) finish();
          },
          error: () => {
            failed++;
            if (done + failed === ids.length) finish();
          },
        });
    }
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
          this.closeConvert();
          // Send the user straight to the new lead so they can fill in
          // the details. The pipeline_stage defaulted to the first
          // stage; they typically want to move it through right away.
          this.router.navigate(['/user/leads'], { queryParams: { q: resp.lead_id } });
        },
        error: (err: HttpErrorResponse) => {
          this.convertSubmitting.set(false);
          this.convertError.set(extractApiError(err) ?? 'Could not convert walk-in.');
        },
      });
  }

  /** Advance a walk-in to a new state. Optimistic — replaces the row
   * on success, reverts on error. */
  protected advanceStatus(walkIn: WalkIn, target: WalkInStatus): void {
    const before = this.state.items();
    // Optimistic update.
    this.state.items.update((rows) =>
      rows.map((w) => (w.id === walkIn.id ? { ...w, status: target } : w)),
    );
    this.api
      .update(walkIn.id, { status: target })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) => rows.map((w) => (w.id === updated.id ? updated : w)));
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set(before);
          this.state.loadError.set(extractApiError(err) ?? 'Could not update walk-in status.');
        },
      });
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
  }

  protected onCheckout(walkIn: WalkIn): void {
    // Optimistic: stamp time_out locally to a near-now ISO so the
    // duration column populates immediately. Replaced by server value.
    const optimisticNow = new Date().toISOString();
    const before = this.state.items();
    this.state.items.update((rows) =>
      rows.map((w) => (w.id === walkIn.id ? { ...w, time_out: optimisticNow } : w)),
    );
    this.api
      .checkout(walkIn.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) => rows.map((w) => (w.id === updated.id ? updated : w)));
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set(before);
          this.state.loadError.set(extractApiError(err) ?? 'Could not check out walk-in.');
        },
      });
  }

  protected statusClass(status: WalkInStatus): string {
    switch (status) {
      case 'browsing':
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
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
    if (iso === null) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'â€”';
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected formatDate(iso: string | null): string {
    if (iso === null) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'â€”';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  /** No users-list API yet â€” show a short id snippet, or "â€”" if unassigned. */
  protected assignedToLabel(id: string | null): string {
    if (id === null) return 'â€”';
    return id.slice(0, 8);
  }

  protected formatDuration(min: string | null): string {
    if (min === null) return 'â€”';
    const n = Number(min);
    if (!Number.isFinite(n)) return 'â€”';
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

  private fetchContacts(ids: string[]): void {
    forkJoin(ids.map((id) => this.contactsApi.get(id).pipe(catchError(() => of(null)))))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of results) {
            if (c) next[c.id] = { id: c.id, full_name: c.full_name, phone: c.phone };
          }
          return next;
        });
      });
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
