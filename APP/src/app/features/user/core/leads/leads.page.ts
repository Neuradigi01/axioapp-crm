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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { forkJoin, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { ContactsApiService } from '../contacts/contacts-api.service';
import {
  ItemMovedEvent,
  PipelineItem,
} from '../pipelines/pipelines-api.service';
import { PipelineBoardComponent } from '../pipelines/pipeline-board.component';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ColumnDef, ColumnPrefsService } from '../shared/column-prefs.service';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { FieldDef } from '../shared/dynamic-form/types';
import { clauseCount, FilterDsl } from '../shared/filter-dsl.types';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import { ReassignConfirm, ReassignModalComponent } from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { AdvancedFilterModalComponent } from './advanced-filter-modal.component';
import { ColumnCustomizationMenuComponent } from './column-customization-menu.component';
import { LeadCardComponent } from './lead-card.component';
import { LeadFormModalComponent } from './lead-form-modal.component';
import {
  LostReasonConfirm,
  LostReasonModalComponent,
} from './lost-reason-modal/lost-reason-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  Lead,
  LeadCreate,
  LeadListQuery,
  LeadSortKey,
  LeadStatus,
  LeadUpdate,
  LeadsApiService,
  SortOrder,
} from './leads-api.service';
import {
  SavedView,
  SavedViewConfig,
  SavedViewsApiService,
} from './saved-views-api.service';

/**
 * Top-level Leads page.
 *
 * Tabs:
 *   - **Pipeline** — wraps `<app-pipeline-board pipelineKey="leads">`
 *     and feeds it the loaded leads. The lead-card template projects
 *     into each kanban card. `(itemMoved)` calls the move-stage
 *     endpoint; on error we revert the optimistic local mutation.
 *   - **List** — wraps `<app-pipeline-list>` for the same data with
 *     the same `itemMoved` semantics. List view layers on the Step 6
 *     power-user kit: cursor pagination, column customization, advanced
 *     filter modal, and CSV export. Pipeline view is intentionally
 *     unpaginated (kanban is per-stage already).
 *
 * Contact info on each card comes from a one-shot
 * `forkJoin(contactsApi.get(id))` after the leads load — keeps the
 * card component dumb and avoids it issuing its own HTTP per render.
 */
type View = 'pipeline' | 'list';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
  source: string | null;
}

/** Default column layout for the list view. The customization menu
 * persists per-user overrides in localStorage via `ColumnPrefsService`. */
const DEFAULT_LEAD_COLUMNS: ColumnDef[] = [
  { key: 'contact_name', label: 'Contact', visible: true },
  { key: 'status', label: 'Status', visible: true },
  { key: 'owner', label: 'Owner', visible: true },
  { key: 'source', label: 'Source', visible: true },
  { key: 'lead_score', label: 'Score', visible: true },
  { key: 'last_activity_at', label: 'Last activity', visible: true },
  { key: 'created_at', label: 'Created', visible: true },
  { key: 'budget', label: 'Budget', visible: false },
  { key: 'phone', label: 'Phone', visible: false },
  { key: 'email', label: 'Email', visible: false },
];

/** Pagination sizes the footer dropdown offers. 200 is the server cap. */
const PAGE_SIZES = [25, 50, 100, 200] as const;

class LeadsListState extends ListPageState<Lead> {}

@Component({
  selector: 'app-leads-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    PipelineBoardComponent,
    LeadCardComponent,
    LeadFormModalComponent,
    RelativeTimePipe,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    UrlFilterStateDirective,
    LostReasonModalComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    ColumnCustomizationMenuComponent,
    AdvancedFilterModalComponent,
  ],
  providers: [LeadsListState],
  templateUrl: './leads.page.html',
})
export class LeadsPageComponent {
  private readonly api = inject(LeadsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly columnPrefs = inject(ColumnPrefsService);
  private readonly savedViewsApi = inject(SavedViewsApiService);

  protected readonly state = inject(LeadsListState);

  /** Gates the "Import" header button; backend enforces too. */
  protected readonly canImport = computed(() =>
    this.auth.currentPermissions().includes('leads.import'),
  );

  /** Gates the "Export CSV" toolbar button; backend enforces too. */
  protected readonly canExport = computed(() =>
    this.auth.currentPermissions().includes('leads.export'),
  );

  readonly view = signal<View>('pipeline');
  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  /** Assignee filter. `''` = all; `'me'` resolves to current user;
   * `'unassigned'` filters `assigned_to_id IS NULL`; UUID = that user. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
  /** Status chip filter: `''` = all, otherwise `active | won | lost`. */
  readonly statusControl = new FormControl<string>('', { nonNullable: true });

  /** Sort state — backend whitelist is created_at / last_activity_at /
   * lead_score / contact_name. Default newest-created first, matches
   * the prior server default so existing users see no change. */
  readonly sortKey = signal<LeadSortKey>('created_at');
  readonly sortOrder = signal<SortOrder>('desc');

  /** "No activity in N days" chip — translates to `last_activity_lt`. */
  readonly noActivityFilter = signal<'' | '7d' | '14d' | '30d'>('');

  /** Visibility scope: which leads to show before any other filter.
   * Junior reps default to "mine" and don't see the toggle; managers
   * default to "team"; admin/owner default to "all". */
  readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());

  /** Cached user list for the assignee dropdown. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup so list rows can render a name
   * without round-tripping per row. */
  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
  });

  // --- Step 6: pagination + columns + advanced filter ---------------------

  /** Cursor-mode page size. List view only — pipeline view fetches
   * size=200 (its kanban needs the union across stages and tops out
   * at the same server cap). Reuses `state.pageSize` from the shared
   * list-page service; default overridden to 50 for the leads list. */
  protected readonly pageSizeOptions = PAGE_SIZES;

  /** Current opaque cursor. `null` = first page. */
  readonly cursor = signal<string | null>(null);

  /** Cursor of the next page, or `null` when the set is exhausted. */
  readonly nextCursor = signal<string | null>(null);

  /** Back-stack of previously visited cursors so "Previous" can walk
   * back. Each entry is the cursor that was active when the page was
   * rendered; popping gives us the cursor to fetch. */
  readonly cursorHistory = signal<(string | null)[]>([]);

  /** Server-reported total. `null` on cursor-only pages (we only ask
   * for it on the first page of a filter set). */
  readonly totalCount = signal<number | null>(null);

  /** 1-based page index, derived from `cursorHistory.length`. */
  readonly currentPage = computed(() => this.cursorHistory().length + 1);

  /** "Showing X–Y of N" — built from page index + page size + total. */
  readonly pageRangeStart = computed(() => {
    if (this.state.items().length === 0) return 0;
    return (this.currentPage() - 1) * this.state.pageSize() + 1;
  });
  readonly pageRangeEnd = computed(
    () => this.pageRangeStart() + this.state.items().length - 1,
  );

  /** Customized columns for the list-view table. */
  readonly columns = signal<ColumnDef[]>(
    this.columnPrefs.get('leads', DEFAULT_LEAD_COLUMNS),
  );
  protected readonly defaultColumns = DEFAULT_LEAD_COLUMNS;
  readonly visibleColumns = computed(() =>
    this.columns().filter((c) => c.visible),
  );
  protected isColumnVisible(key: string): boolean {
    return this.visibleColumns().some((c) => c.key === key);
  }

  /** Advanced filter DSL — emitted by the modal on Apply. Empty
   * object means no DSL clauses (convenience filters still apply). */
  readonly advancedFilter = signal<FilterDsl>({});
  readonly advancedFilterOpen = signal(false);
  readonly advancedFilterCount = computed(() => clauseCount(this.advancedFilter()));

  /** Custom field definitions for the org. Fetched once on mount to
   * feed the advanced-filter modal's field picker. */
  readonly customFields = signal<FieldDef[]>([]);

  /** CSV export submit state. */
  readonly exporting = signal(false);
  readonly exportError = signal<string | null>(null);

  // --- Step 7: saved views ------------------------------------------------

  /** All views the current user can see for `entity='leads'` — owned
   * first, then shared. Backend already sorts; we re-bucket for the
   * popover. Refreshed via `reloadSavedViews()` after any mutation. */
  readonly savedViews = signal<SavedView[]>([]);

  /** Currently applied view id, or `null` when the user is on the
   * default (unsaved) page state. Set by `applyView`; cleared whenever
   * the user changes a filter/sort/scope/column manually. */
  readonly currentViewId = signal<string | null>(null);

  /** Resolved view object — `null` when no view is active. */
  readonly currentView = computed<SavedView | null>(() => {
    const id = this.currentViewId();
    if (!id) return null;
    return this.savedViews().find((v) => v.id === id) ?? null;
  });

  /** Display name in the toolbar trigger. */
  readonly currentViewName = computed<string | null>(
    () => this.currentView()?.name ?? null,
  );

  /** True when the active view belongs to the current user (gates the
   * "Update / Delete this view" affordances). Shared views applied by
   * non-owners are read-only. */
  readonly isCurrentViewOwner = computed(() => {
    const view = this.currentView();
    if (!view) return false;
    return view.owner_user_id === this.auth.currentUserId();
  });

  /** Popover open/closed. */
  readonly viewsMenuOpen = signal(false);

  /** Mini "Save view" modal state. `null` = closed. */
  readonly saveViewModalOpen = signal(false);
  readonly saveViewName = signal('');
  readonly saveViewShared = signal(false);
  readonly saveViewSubmitting = signal(false);
  readonly saveViewError = signal<string | null>(null);

  /** Delete-view confirm dialog visibility. */
  readonly deleteViewConfirmOpen = signal(false);
  readonly deleteViewSubmitting = signal(false);

  // --- Existing state -----------------------------------------------------

  private readonly q = toSignal(
    this.searchControl.valueChanges.pipe(debounceTime(200), distinctUntilChanged()),
    { initialValue: '' },
  );
  private readonly sourceFilter = toSignal(
    this.sourceControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  readonly sourceOptions = computed(() => {
    const set = new Set<string>();
    for (const c of Object.values(this.contactsById())) {
      if (c.source) set.add(c.source);
    }
    return [...set].sort();
  });

  /** Header subtitle counts: `loadedCount` is what's on screen now,
   * `totalCount` is server-reported for the active filter. */
  readonly loadedCount = computed(() => this.state.items().length);
  readonly newTodayCount = computed(() => {
    const todayKey = this.todayKey();
    return this.state.items().filter(
      (l) => this.dateKey(l.created_at) === todayKey,
    ).length;
  });

  private todayKey(): string {
    return this.dateKey(new Date().toISOString());
  }

  private dateKey(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  /** Modal: null = closed, undefined = create, Lead = edit. */
  readonly modalState = signal<Lead | null | undefined>(null);
  readonly modalOpen = computed(() => this.modalState() !== null);
  readonly editingLead = computed<Lead | null>(() => {
    const v = this.modalState();
    return v === undefined ? null : (v ?? null);
  });
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  // --- Multi-select + bulk + reassign state -------------------------------

  /** Row ids selected on the list view. Pipeline board has its own
   * single-click-pencil reassign; bulk select only runs on list. Lives
   * on `state.selectedIds` (with `state.selectedCount` derived). */

  /** Which bulk-action modal is open (one at a time). Lives on
   * `state.bulkModal`; values are still `'reassign' | 'delete' | null`. */

  /** Single-row reassign (from the pencil on a card or list row). */
  readonly singleReassignLead = signal<Lead | null>(null);
  readonly singleReassignSubmitting = signal(false);
  readonly singleReassignError = signal<string | null>(null);

  /** Pending move-stage that's waiting on a Lost-reason. The Step 1
   * backend rejects a move into an `is_lost=true` stage with 422 and
   * a known detail; we catch that, snapshot the move here, open the
   * `LostReasonModal`, and re-issue with the reason on confirm. */
  readonly pendingLostMove = signal<ItemMovedEvent | null>(null);
  readonly lostReasonSubmitting = signal(false);
  readonly lostReasonError = signal<string | null>(null);

  /** URL ↔ state map for the filter chip strip + filter row + view +
   * page. Refresh / share / browser-back all preserve the view.
   * Pagination cursor is intentionally NOT URL-persisted: the cursor
   * is opaque and stale-prone (it encodes the sort-column value of
   * the last row, so a row mutation invalidates the cursor). Filters,
   * sort, scope, and view ARE persisted — that's the useful slice. */
  readonly urlState: UrlFilterStateConfig = {
    q: {
      read: () => this.searchControl.value,
      write: (v) => this.searchControl.setValue(v),
      queryKey: 'q',
    },
    source: {
      read: () => this.sourceControl.value,
      write: (v) => this.sourceControl.setValue(v),
      queryKey: 'source',
    },
    status: {
      read: () => this.statusControl.value,
      write: (v) => this.statusControl.setValue(v),
      queryKey: 'status',
    },
    assignee: {
      read: () => this.assigneeControl.value,
      write: (v) => this.assigneeControl.setValue(v),
      queryKey: 'assignee',
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
        if (
          v === 'created_at' ||
          v === 'last_activity_at' ||
          v === 'lead_score' ||
          v === 'contact_name'
        ) {
          this.sortKey.set(v);
        }
      },
      queryKey: 'sort',
      defaultValue: 'created_at',
    },
    order: {
      read: () => this.sortOrder(),
      write: (v) => {
        if (v === 'asc' || v === 'desc') this.sortOrder.set(v);
      },
      queryKey: 'order',
      defaultValue: 'desc',
    },
    no_activity: {
      read: () => this.noActivityFilter(),
      write: (v) => {
        if (v === '' || v === '7d' || v === '14d' || v === '30d') {
          this.noActivityFilter.set(v);
        }
      },
      queryKey: 'no_activity',
    },
    view: {
      read: () => this.view(),
      write: (v) => {
        if (v === 'pipeline' || v === 'list') this.view.set(v);
      },
      queryKey: 'view',
      defaultValue: 'pipeline',
    },
  };

  /** Cast Lead[] to PipelineItem[] for the board/list inputs. */
  readonly pipelineItems = computed<PipelineItem[]>(
    () => this.state.items() as PipelineItem[],
  );

  constructor() {
    this.state.bulkActions.set([
      { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'leads.reassign' },
      { key: 'delete', label: 'Delete', icon: 'trash-2', danger: true, permissionKey: 'leads.write' },
    ]);
    // Leads list defaults to 50 rows; shared service defaults to 25.
    this.state.pageSize.set(50);
    this.reload();
    this.loadCustomFields();
    this.reloadSavedViews();

    // Filter changes trigger re-fetch.
    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());
    this.sourceControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());
    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());
    this.statusControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());

    // Whenever leads change, fetch any contacts we don't already have cached.
    effect(() => {
      const ids = new Set(this.state.items().map((l) => l.contact_id));
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });

    // Honour `/user/leads?new=1` (used by the global quick-add FAB) so
    // landing on the page from anywhere in the app drops the user
    // straight into the create-lead modal. Strip the param after
    // consuming it so a refresh doesn't re-open.
    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        if (params.get('new') !== null && this.modalState() === null) {
          this.openCreate();
          this.router.navigate([], {
            relativeTo: this.route,
            queryParams: { new: null },
            queryParamsHandling: 'merge',
            replaceUrl: true,
          });
        }
      });
  }

  protected setView(v: View): void {
    this.view.set(v);
  }

  /** Build the query for the current page. List view uses cursor
   * pagination + the advanced filter DSL; pipeline view skips both
   * (it fetches the union across all stages at the server cap, the
   * same way it did before Step 6). */
  protected buildQuery(): LeadListQuery {
    const base: LeadListQuery = {
      q: this.q() || undefined,
      source: this.sourceFilter() || undefined,
      status: (this.statusControl.value as LeadStatus) || undefined,
      assigned_to: this.resolveAssignee(),
      last_activity_lt: this.resolveNoActivityCutoff() ?? undefined,
      sort: this.sortKey(),
      order: this.sortOrder(),
    };
    if (this.advancedFilterCount() > 0) {
      base.filter = this.advancedFilter();
    }
    if (this.view() === 'list') {
      base.limit = this.state.pageSize();
      base.cursor = this.cursor();
      // Only ask for the count on the first page so the COUNT(*) hit
      // is amortised across the whole walk. The server returns `null`
      // for `total` on subsequent pages.
      base.with_total = this.cursorHistory().length === 0;
    } else {
      // Pipeline view: keep the existing one-shot bulk fetch.
      base.size = 200;
      base.with_total = true;
    }
    return base;
  }

  protected reload(): void {
    this.state.loading.set(true);
    this.state.loadError.set(null);
    this.api
      .list(this.buildQuery())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.state.items.set(resp.items);
          this.nextCursor.set(resp.next_cursor);
          if (resp.total !== null && resp.total !== undefined) {
            this.totalCount.set(resp.total);
          }
          this.state.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set([]);
          this.nextCursor.set(null);
          this.state.loading.set(false);
          this.state.loadError.set(extractApiError(err) ?? 'Could not load leads.');
        },
      });
  }

  /** Reset the cursor stack before re-issuing — any filter / sort
   * change invalidates the keyset bounds. */
  protected resetCursorAndReload(): void {
    this.cursor.set(null);
    this.cursorHistory.set([]);
    this.totalCount.set(null);
    this.reload();
  }

  // --- Step 6: pagination handlers ---------------------------------------

  protected onNextPage(): void {
    const next = this.nextCursor();
    if (!next) return;
    this.cursorHistory.update((stack) => [...stack, this.cursor()]);
    this.cursor.set(next);
    this.reload();
  }

  protected onPrevPage(): void {
    const stack = this.cursorHistory();
    if (stack.length === 0) return;
    const prev = stack[stack.length - 1];
    this.cursorHistory.set(stack.slice(0, -1));
    this.cursor.set(prev);
    this.reload();
  }

  protected onPageSizeChange(value: string): void {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return;
    if (!PAGE_SIZES.includes(n as (typeof PAGE_SIZES)[number])) return;
    this.state.pageSize.set(n);
    this.resetCursorAndReload();
  }

  protected canGoNext = computed(() => this.nextCursor() !== null);
  protected canGoPrev = computed(() => this.cursorHistory().length > 0);

  // --- Step 6: column customization handlers -----------------------------

  protected onColumnsChange(cols: ColumnDef[]): void {
    this.columns.set(cols);
    this.columnPrefs.set('leads', cols);
  }

  // --- Step 6: advanced filter handlers ----------------------------------

  protected openAdvancedFilter(): void {
    this.advancedFilterOpen.set(true);
  }

  protected closeAdvancedFilter(): void {
    this.advancedFilterOpen.set(false);
  }

  protected onAdvancedFilterApply(dsl: FilterDsl): void {
    this.advancedFilter.set(dsl);
    this.advancedFilterOpen.set(false);
    this.resetCursorAndReload();
  }

  // --- Step 6: CSV export ------------------------------------------------

  protected onExportCsv(): void {
    if (!this.canExport()) return;
    this.exporting.set(true);
    this.exportError.set(null);
    this.api
      .exportCsv(this.buildQuery())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.exporting.set(false);
          this.api.triggerDownload(blob, this.suggestedExportFilename());
        },
        error: (err: HttpErrorResponse) => {
          this.exporting.set(false);
          this.exportError.set(
            extractApiError(err) ?? 'Could not export leads.',
          );
        },
      });
  }

  /** UTC-dated default; the server's `Content-Disposition` overrides
   * via the helper but only when the response is parsed — for blob
   * downloads we set the filename ourselves. */
  private suggestedExportFilename(): string {
    const d = new Date();
    const iso = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
    return `leads-${iso}.csv`;
  }

  private loadCustomFields(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (fields) => this.customFields.set(fields),
        error: () => {
          // Non-fatal — the modal just won't show custom-field options.
          this.customFields.set([]);
        },
      });
  }

  // --- Step 7: saved views ------------------------------------------------

  private reloadSavedViews(): void {
    this.savedViewsApi
      .list('leads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (views) => this.savedViews.set(views),
        error: () => this.savedViews.set([]),
      });
  }

  /** Snapshot the current page state into a `SavedViewConfig`. The
   * leads page is the only consumer right now so this is inline; when
   * walk-ins / contacts wire up saved views, lift to a strategy on the
   * API service. */
  private buildCurrentConfig(): SavedViewConfig {
    return {
      filter: this.advancedFilterCount() > 0 ? this.advancedFilter() : undefined,
      sort: this.sortKey(),
      order: this.sortOrder(),
      scope: this.scope(),
      columns: this.columns(),
      view: this.view(),
    };
  }

  protected toggleViewsMenu(): void {
    this.viewsMenuOpen.update((v) => !v);
  }

  protected closeViewsMenu(): void {
    this.viewsMenuOpen.set(false);
  }

  /** Restore every saved slice of state. Missing keys keep the current
   * value — that lets the menu apply a "partial" view (e.g. "just sort
   * by score, leave my columns alone") without re-spec'ing the UI. */
  protected applyView(view: SavedView): void {
    const cfg = view.config ?? {};
    if (cfg.filter && Object.keys(cfg.filter).length > 0) {
      this.advancedFilter.set(cfg.filter);
    } else {
      this.advancedFilter.set({});
    }
    if (cfg.sort) {
      const k = cfg.sort;
      if (
        k === 'created_at' ||
        k === 'last_activity_at' ||
        k === 'lead_score' ||
        k === 'contact_name'
      ) {
        this.sortKey.set(k);
      }
    }
    if (cfg.order === 'asc' || cfg.order === 'desc') {
      this.sortOrder.set(cfg.order);
    }
    if (cfg.scope === 'mine' || cfg.scope === 'team' || cfg.scope === 'all') {
      this.scope.set(cfg.scope);
    }
    if (cfg.columns && cfg.columns.length > 0) {
      this.columns.set(cfg.columns);
      this.columnPrefs.set('leads', cfg.columns);
    }
    if (cfg.view === 'list' || cfg.view === 'pipeline') {
      this.view.set(cfg.view);
    }
    this.currentViewId.set(view.id);
    this.viewsMenuOpen.set(false);
    this.cursor.set(null);
    this.cursorHistory.set([]);
    this.totalCount.set(null);
    this.reload();
  }

  protected openSaveViewModal(): void {
    this.saveViewName.set(this.currentView()?.name ?? '');
    this.saveViewShared.set(this.currentView()?.shared ?? false);
    this.saveViewError.set(null);
    this.saveViewModalOpen.set(true);
    this.viewsMenuOpen.set(false);
  }

  protected closeSaveViewModal(): void {
    this.saveViewModalOpen.set(false);
    this.saveViewSubmitting.set(false);
    this.saveViewError.set(null);
  }

  protected onSaveViewNameInput(value: string): void {
    this.saveViewName.set(value);
  }

  protected onSaveViewSharedChange(value: boolean): void {
    this.saveViewShared.set(value);
  }

  protected submitSaveView(): void {
    const name = this.saveViewName().trim();
    if (!name) {
      this.saveViewError.set('Please enter a name for this view.');
      return;
    }
    this.saveViewSubmitting.set(true);
    this.saveViewError.set(null);
    this.savedViewsApi
      .create({
        entity: 'leads',
        name,
        config: this.buildCurrentConfig(),
        shared: this.saveViewShared(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (view) => {
          this.savedViews.update((rows) => [...rows, view]);
          this.currentViewId.set(view.id);
          this.closeSaveViewModal();
        },
        error: (err: HttpErrorResponse) => {
          this.saveViewSubmitting.set(false);
          // The backend returns 409 with `detail` set when the unique
          // (owner, entity, name) constraint trips. Surface the original
          // detail so the user can rename.
          if (err.status === 409) {
            this.saveViewError.set(
              extractApiError(err) ?? 'You already have a view by that name.',
            );
          } else {
            this.saveViewError.set(
              extractApiError(err) ?? 'Could not save view.',
            );
          }
        },
      });
  }

  /** Overwrite the active view with the current page state. Only callable
   * when the caller owns the active view (the button is gated). */
  protected updateCurrentView(): void {
    const view = this.currentView();
    if (!view || !this.isCurrentViewOwner()) return;
    this.savedViewsApi
      .update(view.id, {
        config: this.buildCurrentConfig(),
        shared: view.shared,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.savedViews.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.viewsMenuOpen.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.state.loadError.set(
            extractApiError(err) ?? 'Could not update view.',
          );
        },
      });
  }

  /** Toggle the active view's `shared` flag without rewriting its
   * config. Bound from the popover's "Share with team" inline switch. */
  protected toggleCurrentViewShared(): void {
    const view = this.currentView();
    if (!view || !this.isCurrentViewOwner()) return;
    this.savedViewsApi
      .update(view.id, { shared: !view.shared })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.savedViews.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.state.loadError.set(
            extractApiError(err) ?? 'Could not change sharing.',
          );
        },
      });
  }

  protected openDeleteViewConfirm(): void {
    if (!this.isCurrentViewOwner()) return;
    this.deleteViewConfirmOpen.set(true);
    this.viewsMenuOpen.set(false);
  }

  protected closeDeleteViewConfirm(): void {
    this.deleteViewConfirmOpen.set(false);
    this.deleteViewSubmitting.set(false);
  }

  protected confirmDeleteView(): void {
    const view = this.currentView();
    if (!view || !this.isCurrentViewOwner()) return;
    this.deleteViewSubmitting.set(true);
    this.savedViewsApi
      .delete(view.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.savedViews.update((rows) =>
            rows.filter((r) => r.id !== view.id),
          );
          this.currentViewId.set(null);
          this.closeDeleteViewConfirm();
        },
        error: (err: HttpErrorResponse) => {
          this.deleteViewSubmitting.set(false);
          this.state.loadError.set(
            extractApiError(err) ?? 'Could not delete view.',
          );
        },
      });
  }

  // --- Existing handlers --------------------------------------------------

  /** Resolve the assignee filter to a value the backend understands.
   * `''` (no filter) → undefined. `'me'` → current user id. `'unassigned'`
   * → undefined (special-case handled in Step 3 with a dedicated server
   * param; for now we surface "All" rows when picked, so the chip is
   * visible but inert until that lands). UUID → that UUID. */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    if (raw === 'unassigned') return undefined;
    return raw;
  }

  /** Translate the no-activity chip to an ISO timestamp the backend
   * `last_activity_lt` param accepts. Returns null when no chip is
   * active so the caller can omit the param. */
  private resolveNoActivityCutoff(): string | null {
    const choice = this.noActivityFilter();
    if (!choice) return null;
    const days = choice === '7d' ? 7 : choice === '14d' ? 14 : 30;
    const cutoff = new Date(Date.now() - days * 86_400_000);
    return cutoff.toISOString();
  }

  protected toggleSort(key: LeadSortKey): void {
    if (this.sortKey() === key) {
      this.sortOrder.update((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortKey.set(key);
      this.sortOrder.set(key === 'contact_name' ? 'asc' : 'desc');
    }
    this.resetCursorAndReload();
  }

  protected setStatus(value: string): void {
    this.statusControl.setValue(value);
  }

  protected setScope(value: string): void {
    if (value !== 'mine' && value !== 'team' && value !== 'all') return;
    this.scope.set(value);
    this.resetCursorAndReload();
  }

  protected setNoActivity(value: string): void {
    if (value !== '' && value !== '7d' && value !== '14d' && value !== '30d') return;
    this.noActivityFilter.set(value);
    this.resetCursorAndReload();
  }

  /** Parse a `<sort>:<order>` token from the sort dropdown and update both
   * signals + reload. Whitelisted to keep the URL state in lockstep with
   * the backend's accepted sort keys. */
  protected setSort(value: string): void {
    const [key, order] = value.split(':');
    if (
      key !== 'created_at' &&
      key !== 'last_activity_at' &&
      key !== 'lead_score' &&
      key !== 'contact_name'
    ) {
      return;
    }
    if (order !== 'asc' && order !== 'desc') return;
    this.sortKey.set(key);
    this.sortOrder.set(order);
    this.resetCursorAndReload();
  }

  /** Default visibility based on the user's role. Junior reps see only
   * their leads; managers see their team; admin/owner see all. Roles
   * the codebase ships with — Owner, Admin, Sales Manager, Employee
   * etc. — are matched by template name. */
  private defaultScopeForRole(): 'mine' | 'team' | 'all' {
    const role = this.auth.currentRoleName();
    if (!role) return 'mine';
    const r = role.toLowerCase();
    if (r === 'owner' || r === 'admin') return 'all';
    if (r.includes('manager')) return 'team';
    return 'mine';
  }

  /** Whether the scope toggle should be visible. Junior staff get the
   * implicit "mine" default with no toggle — keeps their view focused. */
  protected readonly canChangeScope = computed(() => {
    const role = this.auth.currentRoleName().toLowerCase();
    return role === 'owner' || role === 'admin' || role.includes('manager');
  });

  /** Tailwind class string for a status pill. */
  protected statusClass(s: LeadStatus): string {
    switch (s) {
      case 'won':
        return 'bg-emerald-100 text-emerald-800 ring-emerald-200';
      case 'lost':
        return 'bg-rose-100 text-rose-800 ring-rose-200';
      default:
        return 'bg-blue-100 text-blue-800 ring-blue-200';
    }
  }

  protected statusLabel(s: LeadStatus): string {
    return s === 'active' ? 'Active' : s === 'won' ? 'Won' : 'Lost';
  }

  /** Color-band the score pill. 0–29 cold zinc, 30–59 warm amber,
   * 60–89 hot orange, 90+ on-fire red. Matches the spec's intuition
   * that warmer = closer to a sale. */
  protected scoreClass(score: number): string {
    if (score >= 90) return 'bg-red-100 text-red-800 ring-red-200';
    if (score >= 60) return 'bg-orange-100 text-orange-800 ring-orange-200';
    if (score >= 30) return 'bg-amber-100 text-amber-800 ring-amber-200';
    return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
  }

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  protected onItemMoved(event: ItemMovedEvent): void {
    const before = this.state.items();
    // Optimistic local update so the kanban doesn't flicker.
    this.state.items.update((rows) =>
      rows.map((r) =>
        r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r,
      ),
    );
    this.api
      .moveStage(event.itemId, event.toStage)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
        },
        error: (err: HttpErrorResponse) => {
          // Backend signals "moving to Lost needs a reason" with a 422
          // whose detail starts with `lost_reason`. Intercept that case:
          // hold the optimistic position, open the lost-reason modal,
          // and re-issue the move with the reason on confirm.
          const detail = extractApiError(err) ?? '';
          if (err.status === 422 && detail.toLowerCase().includes('lost_reason')) {
            this.pendingLostMove.set(event);
            this.lostReasonError.set(null);
            return;
          }
          this.state.items.set(before);
          this.state.loadError.set(detail || 'Could not move lead.');
        },
      });
  }

  protected onLostReasonConfirm(payload: LostReasonConfirm): void {
    const move = this.pendingLostMove();
    if (!move) return;
    this.lostReasonSubmitting.set(true);
    this.lostReasonError.set(null);
    this.api
      .moveStage(move.itemId, move.toStage, {
        lost_reason: payload.lost_reason,
        lost_reason_other: payload.lost_reason_other,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.lostReasonSubmitting.set(false);
          this.pendingLostMove.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.lostReasonSubmitting.set(false);
          this.lostReasonError.set(
            extractApiError(err) ?? 'Could not mark lead as Lost.',
          );
        },
      });
  }

  protected onLostReasonCancel(): void {
    // User backed out — undo the optimistic stage move.
    const move = this.pendingLostMove();
    if (move) {
      this.pendingLostMove.set(null);
      this.lostReasonError.set(null);
      this.lostReasonSubmitting.set(false);
      // Re-fetch the row from the server to revert any local state.
      this.reload();
    }
  }

  protected openCreate(): void {
    this.formError.set(null);
    this.modalState.set(undefined);
  }

  protected openEdit(lead: Lead): void {
    this.formError.set(null);
    this.modalState.set(lead);
  }

  protected closeModal(): void {
    this.modalState.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: {
    create?: LeadCreate;
    update?: LeadUpdate;
    moveStageTo?: string;
  }): void {
    if (event.create) {
      this.submitCreate(event.create);
    } else if (event.update) {
      const existing = this.editingLead();
      if (existing) this.submitUpdate(existing.id, event.update, event.moveStageTo);
    }
  }

  protected contactFor(id: string): ContactSummary | null {
    return this.contactsById()[id] ?? null;
  }

  protected statusFor(status: LeadStatus): string {
    return status;
  }

  private submitCreate(payload: LeadCreate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not create lead.');
        },
      });
  }

  private submitUpdate(id: string, payload: LeadUpdate, moveStageTo?: string): void {
    this.submitting.set(true);
    this.formError.set(null);
    const update$ = this.api.update(id, payload);
    const final$ = moveStageTo
      ? update$.pipe(switchMap(() => this.api.moveStage(id, moveStageTo)))
      : update$;
    final$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save lead.');
        },
      });
  }

  // --- Single reassign (pencil on a card / list row) ----------------------

  protected openSingleReassign(lead: Lead): void {
    this.singleReassignError.set(null);
    this.singleReassignLead.set(lead);
  }

  protected closeSingleReassign(): void {
    this.singleReassignLead.set(null);
    this.singleReassignSubmitting.set(false);
    this.singleReassignError.set(null);
  }

  protected onSingleReassign(payload: ReassignConfirm): void {
    const lead = this.singleReassignLead();
    if (!lead) return;
    this.singleReassignSubmitting.set(true);
    this.singleReassignError.set(null);
    this.api
      .reassign(lead.id, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.singleReassignSubmitting.set(false);
          // Replace just the touched row in place so the kanban doesn't
          // flicker its full re-layout for a single owner change.
          this.state.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.closeSingleReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.singleReassignSubmitting.set(false);
          this.singleReassignError.set(
            extractApiError(err) ?? 'Could not reassign lead.',
          );
        },
      });
  }

  // --- Bulk select (list view only) ----------------------------------------

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

  protected onBulkDelete(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkDelete(ids)
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
          this.state.bulkError.set(extractApiError(err) ?? 'Could not delete.');
        },
      });
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(
      ids.map((id) =>
        this.contactsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of results) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
                source: c.source,
              };
            }
          }
          return next;
        });
      });
  }

}
