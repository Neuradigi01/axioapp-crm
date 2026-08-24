import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injectable,
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
import { of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { Contact, ContactsApiService } from '../contacts/contacts-api.service';
import {
  ItemMovedEvent,
  PipelineItem,
  PipelineStage,
  PipelinesApiService,
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
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { AdvancedFilterModalComponent } from './advanced-filter-modal.component';
import { ColumnCustomizationMenuComponent } from './column-customization-menu.component';
import { LeadCardComponent } from './lead-card.component';
import { LeadFormModalComponent } from './lead-form-modal.component';
import { UpdateStatusModalComponent } from './update-status-modal.component';
import {
  LostReasonConfirm,
  LostReasonModalComponent,
} from './lost-reason-modal/lost-reason-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../shared/components/toast/toast.service';
import {
  Lead,
  LeadCreate,
  LeadListQuery,
  LeadSortKey,
  LeadStatus,
  LeadUpdate,
  LeadsApiService,
  PipelineValueRollup,
  SortOrder,
} from './leads-api.service';
import { SavedView, SavedViewConfig, SavedViewsApiService } from './saved-views-api.service';
import {
  WonCaptureConfirm,
  WonCaptureModalComponent,
} from './won-capture-modal/won-capture-modal.component';

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

@Injectable()
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
    UpdateStatusModalComponent,
    RelativeTimePipe,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    UrlFilterStateDirective,
    LostReasonModalComponent,
    WonCaptureModalComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    ColumnCustomizationMenuComponent,
    AdvancedFilterModalComponent,
    MobileSelectComponent,
    MobileDateTimeComponent,
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
  private readonly toast = inject(ToastService);

  protected readonly state = inject(LeadsListState);

  /** Gates the "Import" header button; backend enforces too. */
  protected readonly canImport = computed(() =>
    this.auth.currentPermissions().includes('leads.import'),
  );

  /** Gates the "Export CSV" toolbar button; backend enforces too. */
  protected readonly canExport = computed(() =>
    this.auth.currentPermissions().includes('leads.export'),
  );

  /** Gates the "Owner" filter dropdown. Only users with ``users.read`` see
   * the org-wide leads list (backend list endpoint clamps everyone else
   * to their own rows — see ``api/src/app/core/leads/router.py``). Showing
   * the dropdown to scoped roles is misleading because picking another
   * owner would return an empty list. */
  protected readonly canFilterByOwner = computed(() =>
    this.auth.currentPermissions().includes('users.read'),
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

  /** Leads Center toolbar: inclusive date range on `created_at`.
   *  Empty string = unbounded on that side. YYYY-MM-DD (the shape a
   *  `<input type="date">` emits) — passed to the backend as-is; the
   *  server UTC-anchors both bounds. */
  readonly createdFromControl = new FormControl<string>('', { nonNullable: true });
  readonly createdToControl = new FormControl<string>('', { nonNullable: true });

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

  /** Server-reported unfiltered total — the tenant's whole leads set.
   *  Requested only on the first page of a filter set (opt-in via
   *  `with_unfiltered_total=true`). Powers the `(filtered/total)`
   *  count in the Leads Center header. `null` until the first
   *  response lands. */
  readonly unfilteredTotal = signal<number | null>(null);

  /** Header label: `"X/Y"` when both counts are known, otherwise the
   *  best partial (`X` alone or `?`). */
  readonly leadsCenterCount = computed<string>(() => {
    const filtered = this.totalCount();
    const unfiltered = this.unfilteredTotal();
    if (filtered !== null && unfiltered !== null) return `${filtered}/${unfiltered}`;
    if (filtered !== null) return `${filtered}`;
    return '';
  });

  /** 1-based page index, derived from `cursorHistory.length`. */
  readonly currentPage = computed(() => this.cursorHistory().length + 1);

  /** "Showing X–Y of N" — built from page index + page size + total. */
  readonly pageRangeStart = computed(() => {
    if (this.state.items().length === 0) return 0;
    return (this.currentPage() - 1) * this.state.pageSize() + 1;
  });
  readonly pageRangeEnd = computed(() => this.pageRangeStart() + this.state.items().length - 1);

  /** Customized columns for the list-view table. */
  readonly columns = signal<ColumnDef[]>(this.columnPrefs.get('leads', DEFAULT_LEAD_COLUMNS));
  protected readonly defaultColumns = DEFAULT_LEAD_COLUMNS;
  readonly visibleColumns = computed(() => this.columns().filter((c) => c.visible));
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
  readonly currentViewName = computed<string | null>(() => this.currentView()?.name ?? null);

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

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  /** Source dropdown options. Contacts store `source` as free-form
   *  text — some rows have raw enum keys ("google_ads"), others have
   *  human labels ("Google Ads"), and casing varies ("facebook" vs
   *  "Facebook Ads"). We collapse everything to a single canonical
   *  label per lowercase key so the dropdown doesn't render the
   *  same source twice under different spellings. `value` is the
   *  ORIGINAL (raw) source string of the first occurrence — that's
   *  what the backend filter matches on. `label` is a display-only
   *  prettified version for the option text. */
  readonly sourceOptions = computed<{ value: string; label: string }[]>(() => {
    const byKey = new Map<string, { value: string; label: string }>();
    for (const c of Object.values(this.contactsById())) {
      if (!c.source) continue;
      const key = c.source.trim().toLowerCase();
      if (!key || byKey.has(key)) continue;
      byKey.set(key, { value: c.source, label: this.prettifySource(c.source) });
    }
    return [...byKey.values()].sort((a, b) => a.label.localeCompare(b.label));
  });

  /** Turn a raw source token like "google_ads" or "walk_in" into a
   *  human-readable label ("Google Ads", "Walk-in"). If the input
   *  already has spaces or mixed case (already a label), leave it
   *  alone. Ad-network suffixes are title-cased consistently. */
  private prettifySource(raw: string): string {
    const trimmed = raw.trim();
    if (!trimmed) return trimmed;
    // Preserve existing multi-word labels (e.g. "Cold Call").
    if (/\s/.test(trimmed) && trimmed !== trimmed.toLowerCase()) return trimmed;
    return trimmed.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  /** `crm-mobile-select` shape for the source filter — same data as
   *  `sourceOptions()` plus the sentinel "All sources" first entry. */
  readonly sourceSelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'All sources' },
    ...this.sourceOptions(),
  ]);

  /** `crm-mobile-select` shape for the assignee filter — sentinel
   *  "All owners" + "Me" + "Unassigned" + one entry per active org user. */
  readonly assigneeSelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'All owners' },
    { value: 'me', label: 'Me' },
    { value: 'unassigned', label: 'Unassigned' },
    ...this.users().map((u) => ({ value: u.id, label: u.full_name })),
  ]);

  /** `crm-mobile-select` shape for the Leads Center Status filter —
   *  sentinel "All statuses" first, then one entry per pipeline stage
   *  (sir's ask: merge legacy Status chips + Category dropdown into
   *  one dropdown that lists every stage). */
  readonly stageSelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'All statuses' },
    ...[...this.pipelineStages()]
      .sort((a, b) => a.display_order - b.display_order)
      .map((s) => ({ value: s.key, label: s.name })),
  ]);

  /** `crm-mobile-select` options for the sort field. Kept in sync with
   *  the backend's `sort` enum + the two `next_follow_up_due` entries
   *  Step 2 added. */
  readonly sortFieldOptions: ReadonlyArray<{ value: LeadSortKey; label: string }> = [
    { value: 'created_at', label: 'Date created' },
    { value: 'last_activity_at', label: 'Last activity' },
    { value: 'lead_score', label: 'Score' },
    { value: 'contact_name', label: 'Contact name' },
    { value: 'next_follow_up_due', label: 'Next follow-up' },
  ];

  readonly orderOptions: ReadonlyArray<{ value: SortOrder; label: string }> = [
    { value: 'desc', label: 'Descending' },
    { value: 'asc', label: 'Ascending' },
  ];

  /** Leads Center Remarks filter — matches any note activity text on
   *  the lead. Server caps at 64 chars. */
  readonly remarksControl = new FormControl<string>('', { nonNullable: true });

  /** Header subtitle counts: `loadedCount` is what's on screen now,
   * `totalCount` is server-reported for the active filter. */
  readonly loadedCount = computed(() => this.state.items().length);
  readonly newTodayCount = computed(() => {
    const todayKey = this.todayKey();
    return this.state.items().filter((l) => this.dateKey(l.created_at) === todayKey).length;
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

  /** Prominent info banner shown at the top of the leads page after a
   *  create call comes back as ``ingest_action: 'merged'`` — the new
   *  submission linked to an existing open lead on the same contact
   *  instead of creating a duplicate. Includes the target lead id so
   *  the banner can render a "View existing lead" jump button; the
   *  vague "list didn't grow" outcome otherwise reads as a silent
   *  failure. Cleared on close, on any next create, and when the
   *  user dismisses the banner. */
  readonly mergedNotice = signal<{ leadId: string; contactName: string | null } | null>(null);

  protected dismissMergedNotice(): void {
    this.mergedNotice.set(null);
  }

  protected openMergedLead(): void {
    const notice = this.mergedNotice();
    if (!notice) return;
    this.mergedNotice.set(null);
    this.router.navigate(['/user/leads', notice.leadId]);
  }

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

  /** Update Status modal (sir's "lead action center"). Opened from the
   *  kanban card / list row pencil — supersedes the old mini reassign
   *  modal for the single-lead flow. Bulk reassign still uses its own
   *  reassign-modal instance below. */
  readonly updateStatusLead = signal<Lead | null>(null);
  readonly updateStatusContact = signal<Contact | null>(null);

  /** Pending move-stage that's waiting on a Lost-reason. The Step 1
   * backend rejects a move into an `is_lost=true` stage with 422 and
   * a known detail; we catch that, snapshot the move here, open the
   * `LostReasonModal`, and re-issue with the reason on confirm. */
  readonly pendingLostMove = signal<ItemMovedEvent | null>(null);
  readonly lostReasonSubmitting = signal(false);
  readonly lostReasonError = signal<string | null>(null);

  /** Pending move-stage waiting on Won-capture (F2). Unlike Lost the
   *  backend doesn't reject — we check `is_won` up-front from the
   *  loaded pipeline stages and open the modal before dispatching. */
  readonly pendingWonMove = signal<ItemMovedEvent | null>(null);
  readonly wonCaptureSubmitting = signal(false);
  readonly wonCaptureError = signal<string | null>(null);

  /** Suggestion feed for the Won modal's "closed amount" input —
   *  seeds with the lead's own `budget`. */
  readonly pendingWonSuggestion = signal<string | null>(null);

  /** Loaded pipeline stages (leads pipeline). Used to check
   *  `is_won` / `is_lost` on the destination stage of a card move
   *  before dispatching. Empty until the pipeline API responds. */
  readonly pipelineStages = signal<PipelineStage[]>([]);

  /** F23 pipeline value roll-up. Fetched on init + on any move-stage /
   *  create / delete so the header stays live. Null while loading. */
  readonly pipelineRollup = signal<PipelineValueRollup | null>(null);
  private readonly pipelinesApi = inject(PipelinesApiService);

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
  readonly pipelineItems = computed<PipelineItem[]>(() => this.state.items() as PipelineItem[]);

  constructor() {
    this.state.bulkActions.set([
      { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'leads.reassign' },
      {
        key: 'delete',
        label: 'Delete',
        icon: 'trash-2',
        danger: true,
        permissionKey: 'leads.write',
      },
    ]);
    // Leads list defaults to 50 rows; shared service defaults to 25.
    this.state.pageSize.set(50);
    this.reload();
    this.loadCustomFields();
    this.reloadSavedViews();
    this.loadPipelineStages();
    this.reloadRollup();

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
    this.createdFromControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());
    this.createdToControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.resetCursorAndReload());
    this.remarksControl.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
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
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
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
    // Read `q` + `source` directly from their FormControls (not from
    // the debounced signals) so a manual "Search" click while typing is
    // in-flight uses the operator's current input instead of the last
    // debounced snapshot. The auto-refetch path still runs through the
    // debounced signals — this only closes the manual-search race.
    const base: LeadListQuery = {
      q: this.searchControl.value.trim() || undefined,
      source: this.sourceControl.value || undefined,
      status: (this.statusControl.value as LeadStatus) || undefined,
      assigned_to: this.resolveAssignee(),
      unassigned_only: this.assigneeControl.value === 'unassigned' ? true : undefined,
      last_activity_lt: this.resolveNoActivityCutoff() ?? undefined,
      created_from: this.createdFromControl.value.trim() || undefined,
      created_to: this.createdToControl.value.trim() || undefined,
      remarks_contains: this.remarksControl.value.trim() || undefined,
      stage: this.stageControlValue() || undefined,
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
      // Leads Center header opts in for the extra tenant-wide count
      // on the first page only (subsequent pages don't need to
      // recompute an unchanged value).
      base.with_unfiltered_total = this.cursorHistory().length === 0;
    } else {
      // Pipeline view: keep the existing one-shot bulk fetch.
      base.size = 200;
      base.with_total = true;
      base.with_unfiltered_total = true;
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
          if (resp.unfiltered_total !== null && resp.unfiltered_total !== undefined) {
            this.unfilteredTotal.set(resp.unfiltered_total);
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

  /** Enter-key affordance for the Data Search + Remarks text inputs.
   *  Every filter auto-refetches on `valueChanges` (see subscriptions
   *  in the constructor); this handler exists so pressing Enter fires
   *  the reload immediately, bypassing the 200ms/300ms debounce. The
   *  visible Search button was removed — filters just work on change. */
  protected onToolbarSearch(): void {
    this.resetCursorAndReload();
  }

  /** Leads Center toolbar Reset button. Clears the new date-range +
   *  the shared filter controls back to defaults + re-fetches. Does
   *  NOT touch scope / saved view / advanced-filter DSL — those have
   *  their own dedicated reset affordances. */
  protected onToolbarReset(): void {
    this.createdFromControl.setValue('', { emitEvent: false });
    this.createdToControl.setValue('', { emitEvent: false });
    this.remarksControl.setValue('', { emitEvent: false });
    this.searchControl.setValue('', { emitEvent: false });
    this.sourceControl.setValue('', { emitEvent: false });
    this.assigneeControl.setValue('', { emitEvent: false });
    this.statusControl.setValue('', { emitEvent: false });
    this.stageControlValue.set('');
    this.noActivityFilter.set('');
    this.sortKey.set('created_at');
    this.sortOrder.set('desc');
    this.resetCursorAndReload();
  }

  /** Toolbar Status cell handler — writes to the same `statusControl`
   *  the legacy chip strip used, so the existing chip strip and the
   *  new toolbar stay in sync. Sir's Status dropdown lists pipeline
   *  stages, so we route into `sortKey` for stage OR into
   *  `statusControl` for the legacy Active/Won/Lost — collision-free
   *  because the values sets don't overlap. Value `""` clears. */
  protected onToolbarStageChange(value: string): void {
    // Pipeline stage keys never overlap with LeadStatus enum values
    // (`active`/`won`/`lost` are enum entries, stage keys are org-
    // configured slugs like `proposal`/`qualified`). Route by set
    // membership.
    const stageKeys = this.pipelineStages().map((s) => s.key);
    if (value === '' || stageKeys.includes(value)) {
      this.stageControlValue.set(value);
      this.resetCursorAndReload();
    }
  }

  /** Leads Center Status dropdown value. Separate from `statusControl`
   *  (the legacy Active/Won/Lost pill) so the toolbar can drive
   *  ``stage`` filtering independently. */
  readonly stageControlValue = signal<string>('');

  /** Sort field dropdown handler — the toolbar splits Order By/As
   *  from Order Type, so we no longer read the "key:order" combined
   *  string. */
  protected setSortField(value: string): void {
    if (
      value === 'created_at' ||
      value === 'last_activity_at' ||
      value === 'lead_score' ||
      value === 'contact_name' ||
      value === 'next_follow_up_due'
    ) {
      this.sortKey.set(value);
      this.resetCursorAndReload();
    }
  }

  protected setSortOrder(value: string): void {
    if (value === 'asc' || value === 'desc') {
      this.sortOrder.set(value);
      this.resetCursorAndReload();
    }
  }

  /** Export-in-Excel handler. Wraps the existing `onExportCsv` — one
   *  entry point either place a caller wants to trigger a download.
   *  Kept as a separate method so the sir's-toolbar link and the
   *  legacy chip-strip button can rename independently. */
  protected onToolbarExport(): void {
    this.onExportCsv();
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
          this.exportError.set(extractApiError(err) ?? 'Could not export leads.');
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
            this.saveViewError.set(extractApiError(err) ?? 'You already have a view by that name.');
          } else {
            this.saveViewError.set(extractApiError(err) ?? 'Could not save view.');
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
          this.savedViews.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.viewsMenuOpen.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.state.loadError.set(extractApiError(err) ?? 'Could not update view.');
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
          this.savedViews.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.state.loadError.set(extractApiError(err) ?? 'Could not change sharing.');
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
          this.savedViews.update((rows) => rows.filter((r) => r.id !== view.id));
          this.currentViewId.set(null);
          this.closeDeleteViewConfirm();
        },
        error: (err: HttpErrorResponse) => {
          this.deleteViewSubmitting.set(false);
          this.state.loadError.set(extractApiError(err) ?? 'Could not delete view.');
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
      key !== 'contact_name' &&
      key !== 'next_follow_up_due'
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
        return 'bg-red-500/10 text-red-400 ring-red-500/20';
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
    return 'bg-surface-2 text-default border-subtle';
  }

  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  protected onItemMoved(event: ItemMovedEvent): void {
    // Debug: temporary. Comment out once persistence is confirmed working.

    console.log('[leads.page] onItemMoved reached', event);
    // F2 — intercept move-to-Won up-front so the Won-capture modal
    // can prompt for close details before the API call fires. Same
    // shape as the Lost interception but proactive (backend doesn't
    // 422 on missing won fields).
    const targetStage = this.pipelineStages().find((s) => s.key === event.toStage);
    if (targetStage?.is_won) {
      const lead = this.state.items().find((r) => r.id === event.itemId) as Lead | undefined;
      // Optimistically flip the local card so the drag feels solid;
      // reverts on cancel via reload().
      this.state.items.update((rows) =>
        rows.map((r) => (r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r)),
      );
      this.pendingWonMove.set(event);
      this.pendingWonSuggestion.set(lead?.budget ?? null);
      this.wonCaptureError.set(null);
      return;
    }

    const before = this.state.items();
    // Optimistic local update so the kanban doesn't flicker.
    this.state.items.update((rows) =>
      rows.map((r) => (r.id === event.itemId ? { ...r, pipeline_stage: event.toStage } : r)),
    );
    this.api
      .moveStage(event.itemId, event.toStage)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          // Roll-up numbers change on any stage move — refresh header.
          this.reloadRollup();
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

  protected onWonCaptureConfirm(payload: WonCaptureConfirm): void {
    const move = this.pendingWonMove();
    if (!move) return;
    this.wonCaptureSubmitting.set(true);
    this.wonCaptureError.set(null);
    this.api
      .moveStage(move.itemId, move.toStage, {
        won_value: payload.won_value,
        close_date: payload.close_date,
        won_reason: payload.won_reason,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.wonCaptureSubmitting.set(false);
          this.pendingWonMove.set(null);
          this.pendingWonSuggestion.set(null);
          this.reloadRollup();
        },
        error: (err: HttpErrorResponse) => {
          this.wonCaptureSubmitting.set(false);
          this.wonCaptureError.set(extractApiError(err) ?? 'Could not mark lead as Won.');
        },
      });
  }

  protected onWonCaptureCancel(): void {
    if (this.pendingWonMove()) {
      this.pendingWonMove.set(null);
      this.pendingWonSuggestion.set(null);
      this.wonCaptureError.set(null);
      this.wonCaptureSubmitting.set(false);
      // Undo the optimistic stage flip by re-fetching.
      this.reload();
    }
  }

  private loadPipelineStages(): void {
    this.pipelinesApi
      .getByKey('leads')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => this.pipelineStages.set(p.stages ?? []),
        // Non-blocking: if the pipeline load fails, the Won-capture
        // interception silently no-ops and the standard move-stage
        // path handles it. The frontend already surfaces load errors
        // elsewhere on this page.
        error: () => this.pipelineStages.set([]),
      });
  }

  private reloadRollup(): void {
    this.api
      .pipelineValue()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => this.pipelineRollup.set(r),
        error: () => {
          // Header is aesthetic — silently hide on failure.
          this.pipelineRollup.set(null);
        },
      });
  }

  /** Format money with the roll-up's currency. Used by the header
   *  strip; kept here (not in a pipe) so the "compact" thousands / lakhs
   *  formatting is one place to tweak. */
  protected formatMoney(raw: string | null | undefined, currency: string): string {
    if (raw == null) return '—';
    const n = Number(raw);
    if (!Number.isFinite(n)) return String(raw);
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency,
        maximumFractionDigits: 0,
        notation: n >= 100000 ? 'compact' : 'standard',
      }).format(n);
    } catch {
      return `${currency} ${n.toLocaleString()}`;
    }
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
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.lostReasonSubmitting.set(false);
          this.pendingLostMove.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.lostReasonSubmitting.set(false);
          this.lostReasonError.set(extractApiError(err) ?? 'Could not mark lead as Lost.');
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
    // Click on a lead row/card navigates to the dedicated detail page
    // (which hosts the full timeline, contact panel, and source
    // attribution). The Edit modal still lives on the detail page
    // itself for in-place field edits.
    this.router.navigate(['/user/leads', lead.id]);
  }

  /** Pointer coords captured on pointerdown of a pipeline card. Used by
   *  `handleCardClick` to distinguish a real click (didn't move) from
   *  the mouseup that ends a CDK drag (moved noticeably). Prevents
   *  navigation from firing after a drop, which would destroy the
   *  page and cancel the in-flight `moveStage` HTTP call. */
  private cardPointerDownX = 0;
  private cardPointerDownY = 0;

  protected onCardPointerDown(event: PointerEvent): void {
    this.cardPointerDownX = event.clientX;
    this.cardPointerDownY = event.clientY;
  }

  protected handleCardClick(lead: Lead, event: MouseEvent): void {
    const dx = Math.abs(event.clientX - this.cardPointerDownX);
    const dy = Math.abs(event.clientY - this.cardPointerDownY);
    // 5px matches CDK's default drag-start threshold. Anything more is
    // treated as a drag (no navigation); ≤ 5px is a click.
    if (dx > 5 || dy > 5) return;
    this.openEdit(lead);
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
    contactAction?: 'created' | 'matched';
    contactName?: string;
  }): void {
    if (event.create) {
      this.submitCreate(event.create, event.contactAction, event.contactName);
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

  private submitCreate(
    payload: LeadCreate,
    contactAction?: 'created' | 'matched',
    contactName?: string,
  ): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.mergedNotice.set(null);
    // Use the header-aware create so we can tell the operator when
    // their form submission MERGED into an existing open lead
    // (touchpoint added to timeline) versus creating a fresh row —
    // otherwise the list "not growing" reads as a silent failure.
    this.api
      .createWithAction(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ lead, action }) => {
          this.submitting.set(false);
          this.closeModal();
          if (action === 'merged') {
            // Prior UX kept the modal open with a small red text at the
            // BOTTOM of a scrollable form section — operators kept missing
            // it and reported "the lead isn't being added, no message
            // shown." Now the modal closes and a prominent info banner
            // pops at the top of the leads page with a jump button so
            // the outcome is unmistakable and immediately actionable.
            const banner = this.contactsById()[payload.contact_id]?.full_name ?? null;
            this.mergedNotice.set({ leadId: lead.id, contactName: banner });
          } else {
            // Fresh lead. Confirm both sides of the create — the lead
            // AND its linked contact — so the operator sees that a new
            // contact was written for them (previously silent).
            this.showLeadCreatedToast(contactAction, contactName);
          }
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not create lead.');
        },
      });
  }

  /** Post-create success toast. Wording depends on whether the linked
   * contact was created fresh alongside the lead, or resolved to an
   * existing contact via the dedup check on phone/email. Falls back to
   * a plain "Lead created" when the modal didn't report which happened
   * (e.g. future callers that skip the contact-resolution step). */
  private showLeadCreatedToast(
    contactAction: 'created' | 'matched' | undefined,
    contactName: string | undefined,
  ): void {
    let subtitle: string | null = null;
    if (contactAction === 'created') {
      subtitle = contactName
        ? `New contact “${contactName}” was also created and linked.`
        : 'A new contact was also created and linked.';
    } else if (contactAction === 'matched') {
      subtitle = contactName
        ? `Linked to existing contact “${contactName}”.`
        : 'Linked to an existing contact.';
    }
    this.toast.success('Lead created', { subtitle, durationMs: 4000 });
  }

  private submitUpdate(id: string, payload: LeadUpdate, moveStageTo?: string): void {
    this.submitting.set(true);
    this.formError.set(null);
    const update$ = this.api.update(id, payload);
    const final$ = moveStageTo
      ? update$.pipe(switchMap(() => this.api.moveStage(id, moveStageTo)))
      : update$;
    final$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
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
    // Sir's ask: the card pencil now opens the full Update Status
    // modal instead of the mini reassign modal. The Owner dropdown in
    // that modal covers the reassign case (with auto-remarks) + lets
    // the rep also change stage / add notes / schedule the next
    // follow-up in one shot. The mini reassign modal is kept as a
    // component for bulk-reassign only (see `state.bulkModal`).
    this.updateStatusContact.set(null);
    this.updateStatusLead.set(lead);
    // Fire-and-forget contact hydrate so the Name / WhatsApp / Email
    // cells inside the modal render prefilled. If it fails the modal
    // still opens with empty contact fields — the rep can type or leave
    // them alone.
    this.contactsApi
      .get(lead.contact_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (contact) => {
          // Only apply if the modal is still showing this lead — otherwise
          // a slow fetch could clobber a newer selection.
          if (this.updateStatusLead()?.id === lead.id) {
            this.updateStatusContact.set(contact);
          }
        },
        error: () => {
          /* silent — modal renders without prefill */
        },
      });
  }

  protected closeUpdateStatus(): void {
    this.updateStatusLead.set(null);
    this.updateStatusContact.set(null);
  }

  /** Update Status modal's `saved` output. Trigger a full refetch —
   *  patching one row in-place is fragile across list + pipeline
   *  views (a stage change can move the card to a different column,
   *  a status filter can drop it off-page entirely). Cheap one-shot
   *  call keeps both surfaces truthful. */
  protected onUpdateStatusSaved(_event: {
    lead: Lead;
    next_follow_up_task_id: string | null;
  }): void {
    this.closeUpdateStatus();
    this.resetCursorAndReload();
  }

  // Legacy single-row reassign handlers kept for the bulk-reassign
  // modal shape below. Not reachable from the card pencil anymore.
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
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.closeSingleReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.singleReassignSubmitting.set(false);
          this.singleReassignError.set(extractApiError(err) ?? 'Could not reassign lead.');
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
    // Batched hydrate collapses N per-id `GET /contacts/{id}` requests
    // into one `POST /contacts/hydrate`. Backend caps id lists at
    // 200; the list size matches the leads page cap so chunking is a
    // no-op today, but we chunk defensively for future page-size
    // bumps.
    const CHUNK = 200;
    for (let i = 0; i < ids.length; i += CHUNK) {
      const slice = ids.slice(i, i + CHUNK);
      this.contactsApi
        .hydrateByIds(slice)
        .pipe(
          catchError(() => of([])),
          takeUntilDestroyed(this.destroyRef),
        )
        .subscribe((results) => {
          this.contactsById.update((cache) => {
            const next = { ...cache };
            for (const c of results) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
                source: c.source,
              };
            }
            return next;
          });
        });
    }
  }
}
