import { CommonModule } from '@angular/common';
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
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { environment } from '../../../../../environments/environment';
import { FurnitureAuthService } from '../auth/auth.service';
import { ToastService } from '../../../../shared/components/toast/toast.service';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { EmptyStateComponent } from '../shared/empty-state/empty-state.component';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { extractApiError } from '@core/services/api-error.util';

import { SavedView, SavedViewConfig, SavedViewsApiService } from '../leads/saved-views-api.service';
import {
  TASK_FOLLOWUP_LABELS,
  TASK_PRIORITY_LABELS,
  Task,
  TaskCounts,
  TaskDueFilter,
  TaskListFilters,
  TaskListResponse,
  TaskPriority,
  TaskSortBy,
  TaskSortDir,
  TasksApiService,
} from './tasks-api.service';
import { TaskAssignee, TaskFormModalComponent } from './task-form-modal.component';

class TasksListState extends ListPageState<Task> {}

type Scope = 'all' | 'mine';
type StatusChip = 'open' | 'overdue' | 'today' | 'done' | 'missed';
/** Accepted from URLs / saved views. `all` / `mine` are the pre-split
 *  chips that combined scope + "open"; they map onto the scope toggle. */
type Chip = StatusChip | 'all' | 'mine';

const CHIP_KEYS: readonly Chip[] = ['open', 'overdue', 'today', 'done', 'missed', 'all', 'mine'];

/** Rows per request; "Load more" fetches the next page. */
const PAGE_SIZE = 100;

interface ChipDef {
  key: StatusChip;
  label: string;
  /** Which `TaskCounts` number badges this chip. */
  count: keyof TaskCounts;
}

const STATUS_CHIPS: readonly ChipDef[] = [
  { key: 'open', label: 'Open', count: 'open' },
  { key: 'overdue', label: 'Overdue', count: 'overdue' },
  { key: 'today', label: 'Due today', count: 'due_today' },
  { key: 'done', label: 'Done', count: 'done' },
  { key: 'missed', label: 'Missed', count: 'missed' },
];

/**
 * `/user/tasks` — standalone Tasks list page.
 *
 * Permission-scoped: caller with `users.read` sees the `All` chip and
 * defaults to it; others see only `Mine`. Filter chips drive a single
 * `TaskFilters` signal; an effect re-fetches when any filter changes.
 *
 * Same component renders for both scopes — the data set differs based
 * on which endpoint the chip routes to.
 */
@Component({
  selector: 'app-tasks-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    LucideAngularModule,
    TaskFormModalComponent,
    BulkActionBarComponent,
    ConfirmDialogComponent,
    ReassignModalComponent,
    UrlFilterStateDirective,
    RelativeTimePipe,
    MobileSelectComponent,
    RouterLink,
    EmptyStateComponent,
  ],
  providers: [TasksListState],
  templateUrl: './tasks.page.html',
})
export class TasksPageComponent {
  private readonly api = inject(TasksApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly confirmDialog = inject(ConfirmDialogService);

  protected readonly state = inject(TasksListState);
  protected readonly priorityLabels = TASK_PRIORITY_LABELS;
  protected readonly followupLabels = TASK_FOLLOWUP_LABELS;

  /** Server-side headline counts for the current scope / owner. */
  protected readonly counts = signal<TaskCounts | null>(null);

  /** Pages loaded so far; "Load more" fetches the next one. */
  private readonly page = signal(1);
  protected readonly loadingMore = signal(false);
  protected readonly hasMore = computed(() => this.state.items().length < this.state.total());

  protected readonly canViewAll = signal(false);
  protected readonly callerUuid = signal<string | null>(null);
  /** Does the current user have `tasks.assign_others`?  Owner / Admin /
   *  Sales Manager get true; Employee / Support Agent get false. Drives
   *  the Assignee dropdown visibility in the task-form modal and hides
   *  bulk-reassign for users who lack delegation rights. */
  protected readonly canAssignOthers = signal<boolean>(false);
  /** Does the current user have `tasks.delete`?  Owner / Admin only.
   *  Hides row delete + bulk delete for Employee / Sales Manager /
   *  Support Agent, whose backend calls would 403 anyway. */
  protected readonly canDelete = signal<boolean>(false);

  protected readonly assignees = signal<TaskAssignee[]>([]);
  protected readonly assigneeMap = computed(() => {
    const m = new Map<string, string>();
    for (const a of this.assignees()) m.set(a.id, a.full_name || a.email);
    return m;
  });

  protected readonly activeChip = signal<StatusChip>('open');
  protected readonly scope = signal<Scope>('mine');
  protected readonly status = signal<TaskListFilters['status']>('open');
  protected readonly dueFilter = signal<TaskDueFilter | undefined>(undefined);
  protected readonly priorityFilter = signal<TaskPriority | undefined>(undefined);
  protected readonly q = signal<string>('');
  protected readonly sortBy = signal<TaskSortBy>('due_at');
  protected readonly sortDir = signal<TaskSortDir>('asc');

  protected readonly searchCtrl = new FormControl('', { nonNullable: true });
  protected readonly togglingId = signal<string | null>(null);

  protected readonly modalOpen = signal(false);
  protected readonly editingTask = signal<Task | null>(null);

  /** Current owner to preselect in the bulk reassign modal — only
   *  resolvable when exactly one row is selected. Mixed selections
   *  keep the modal's Unassigned default because different rows
   *  can have different owners. */
  protected readonly bulkReassignPresetOwnerId = computed<string | null>(() => {
    const ids = this.state.selectedIds();
    if (ids.size !== 1) return null;
    const [only] = ids;
    return this.state.items().find((t) => t.id === only)?.assigned_to_id ?? null;
  });

  // T2 — single-row delete confirmation.
  protected readonly deletingTask = signal<Task | null>(null);
  protected readonly deleteSubmitting = signal(false);

  // Mark-complete confirmation. Only fires when flipping open → done
  // (destructive-ish: fires a webhook + email to the assignee).
  // Re-opening a done task is silent since the action is safe to undo.
  protected readonly completingTask = signal<Task | null>(null);

  // Row-action confirmations — Snooze +1d / Snooze +1w / Mark missed.
  // The three used to fire instantly on click; the confirm step
  // prevents accidental clicks that would shift the customer's
  // follow-up date or terminally close the task without an undo.
  protected readonly snoozingTomorrowTask = signal<Task | null>(null);
  protected readonly snoozingWeekTask = signal<Task | null>(null);
  protected readonly missingTask = signal<Task | null>(null);

  // T15 — saved views for the tasks list.
  private readonly savedViewsApi = inject(SavedViewsApiService);
  protected readonly savedViews = signal<SavedView[]>([]);
  protected readonly currentViewId = signal<string | null>(null);
  protected readonly currentViewName = signal<string | null>(null);
  protected readonly viewsMenuOpen = signal(false);
  protected readonly saveViewOpen = signal(false);
  protected readonly saveViewName = new FormControl('', { nonNullable: true });
  protected readonly saveViewShared = signal(false);
  protected readonly isCurrentViewOwner = computed(() => {
    const id = this.currentViewId();
    if (!id) return false;
    const v = this.savedViews().find((x) => x.id === id);
    return v?.owner_user_id === this.callerUuid();
  });

  // --- Assignee dropdown (Step 2) ----------------------------------------

  /** Owner filter — `'' | 'me' | <uuid>`. Orthogonal to chips: chips set
   * scope (mine vs all + status/due), this narrows whatever scope is
   * showing to one user. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** Directory of org users for the dropdown. Cached by `UsersDirectoryService`,
   * so this is cheap to read across the page. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** `crm-mobile-select` shape for the Owner filter. */
  readonly assigneeSelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'All owners' },
    { value: 'me', label: 'Me' },
    ...this.users().map((u) => ({ value: u.id, label: u.full_name })),
  ]);

  // --- URL state (Step 2) ------------------------------------------------

  readonly urlState: UrlFilterStateConfig = {
    chip: {
      read: () => this.activeChip(),
      write: (v) => {
        // Keep in sync with the `Chip` union at the top of the file —
        // omitting a valid chip here silently no-ops the URL round-trip
        // and drops the chip's persistence (deep links + refresh reset
        // to the default). `missed` was the missing member.
        if ((CHIP_KEYS as readonly string[]).includes(v)) this.selectChip(v as Chip);
      },
      queryKey: 'chip',
      defaultValue: 'open',
    },
    scope: {
      read: () => this.scope(),
      // Applied for real once /me says whether "All" is allowed.
      write: (v) => {
        if (v === 'all' || v === 'mine') this.scope.set(v);
      },
      queryKey: 'scope',
    },
    assignee: {
      read: () => this.assigneeControl.value,
      write: (v) => this.assigneeControl.setValue(v),
      queryKey: 'assignee',
    },
    sort_by: {
      read: () => this.sortBy(),
      write: (v) => {
        if (
          v === 'due_at' ||
          v === 'priority' ||
          v === 'title' ||
          v === 'created_at' ||
          v === 'last_activity_at'
        ) {
          this.sortBy.set(v);
        }
      },
      queryKey: 'sort',
      defaultValue: 'due_at',
    },
    sort_dir: {
      read: () => this.sortDir(),
      write: (v) => {
        if (v === 'asc' || v === 'desc') this.sortDir.set(v);
      },
      queryKey: 'order',
      defaultValue: 'asc',
    },
  };

  protected readonly chips = STATUS_CHIPS;

  /** Sort choices for the phone layout (the desktop table sorts from
   *  its headers). Value is `<sort_by>:<sort_dir>`. */
  protected readonly sortSelectOptions: ReadonlyArray<{ value: string; label: string }> = [
    { value: 'due_at:asc', label: 'Due soonest' },
    { value: 'due_at:desc', label: 'Due latest' },
    { value: 'priority:asc', label: 'Highest priority' },
    { value: 'created_at:desc', label: 'Newest' },
    { value: 'created_at:asc', label: 'Oldest' },
    { value: 'last_activity_at:desc', label: 'Recent activity' },
    { value: 'title:asc', label: 'Title A–Z' },
  ];

  /** Signal mirror of the owner dropdown for computeds. */
  private readonly assigneeValue = toSignal(this.assigneeControl.valueChanges, {
    initialValue: this.assigneeControl.value,
  });

  /** True when anything beyond the default "Open" view narrows the list —
   *  picks between the "no matches" and "all caught up" empty states. */
  protected readonly hasActiveFilters = computed(
    () =>
      this.activeChip() !== 'open' ||
      !!this.q() ||
      !!this.assigneeValue() ||
      this.priorityFilter() !== undefined,
  );

  constructor() {
    this.state.bulkActions.set([
      // Delegation gate — Employees can only own their own tasks and
      // must not see the Reassign bulk action. Backend rejects the
      // POST anyway, but hiding the button here avoids the confusing
      // "why did this fail?" moment.
      {
        key: 'reassign',
        label: 'Reassign to…',
        icon: 'user-cog',
        permissionKey: 'tasks.assign_others',
      },
      { key: 'done', label: 'Mark done', icon: 'check-circle-2', permissionKey: 'tasks.write' },
      {
        key: 'delete',
        label: 'Delete',
        icon: 'trash-2',
        danger: true,
        permissionKey: 'tasks.delete',
      },
    ]);
    // Decide scope branch from /me, then load assignees + first page.
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => {
          const canView = me.permission_keys.includes('users.read');
          this.canViewAll.set(canView);
          this.canAssignOthers.set(me.permission_keys.includes('tasks.assign_others'));
          this.canDelete.set(me.permission_keys.includes('tasks.delete'));
          this.callerUuid.set(me.id);
          // Scope: a deep-linked `?scope=` wins when the role allows it,
          // otherwise the role default. Then the deep-linked chip.
          const params = this.route.snapshot.queryParamMap;
          const urlScope = params.get('scope');
          this.scope.set(
            urlScope === 'mine' || (urlScope === 'all' && canView)
              ? urlScope
              : canView
                ? 'all'
                : 'mine',
          );
          const urlChip = params.get('chip') as Chip | null;
          this.selectChip(urlChip !== null && CHIP_KEYS.includes(urlChip) ? urlChip : 'open');
          this.openFromLink(params.get('new') !== null, params.get('task'));
          if (canView) this.loadAssignees();
          this.fetch();
          this.reloadSavedViews();
        },
        error: () => {
          this.state.loadError.set('Could not load your profile.');
        },
      });

    this.searchCtrl.valueChanges
      .pipe(debounceTime(250), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => {
        this.q.set((v ?? '').trim());
        this.fetch();
      });

    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.fetch());

    // Re-fetch whenever any of the filter signals change. The first
    // run is suppressed because nothing is set up yet — guarded by
    // checking callerUuid().
    effect(() => {
      // Read every filter signal so the effect tracks them.
      this.scope();
      this.status();
      this.dueFilter();
      this.priorityFilter();
      this.q();
      this.sortBy();
      this.sortDir();
      if (this.callerUuid()) this.fetch();
    });
  }

  protected selectChip(chip: Chip): void {
    let key: StatusChip;
    if (chip === 'all' || chip === 'mine') {
      this.setScope(chip);
      key = 'open';
    } else {
      key = chip;
    }
    this.activeChip.set(key);

    switch (key) {
      case 'open':
        this.status.set('open');
        this.dueFilter.set(undefined);
        break;
      case 'overdue':
        this.status.set('open');
        this.dueFilter.set('overdue');
        break;
      case 'today':
        this.status.set('open');
        this.dueFilter.set('today');
        break;
      case 'done':
        this.status.set('done');
        this.dueFilter.set(undefined);
        break;
      case 'missed':
        // Missed = the operator hit the "Mark as missed" button. It's
        // a terminal status like `done`, but tracked separately so
        // "why wasn't this followed up?" reviews can find them without
        // wading through completed work.
        this.status.set('missed');
        this.dueFilter.set(undefined);
        break;
    }
  }

  /** Mine | All toggle. "All" needs `users.read`; switching to Mine
   *  clears an owner pick (the owner filter only applies to All). */
  protected setScope(value: Scope): void {
    if (value === 'all' && !this.canViewAll()) value = 'mine';
    this.scope.set(value);
    if (value === 'mine' && this.assigneeControl.value) this.assigneeControl.setValue('');
  }

  /** Back to the default view: Open, no search, no owner, no priority. */
  protected clearFilters(): void {
    this.priorityFilter.set(undefined);
    this.selectChip('open');
    if (this.assigneeControl.value) this.assigneeControl.setValue('');
    if (this.searchCtrl.value) this.searchCtrl.setValue('');
  }

  protected onSortSelect(value: string): void {
    const [by, dir] = value.split(':') as [TaskSortBy, TaskSortDir];
    this.sortBy.set(by);
    this.sortDir.set(dir);
  }

  /** `aria-sort` for a sortable header. */
  protected ariaSort(column: TaskSortBy): 'ascending' | 'descending' | 'none' {
    if (this.sortBy() !== column) return 'none';
    return this.sortDir() === 'asc' ? 'ascending' : 'descending';
  }

  protected setSort(column: TaskSortBy): void {
    if (this.sortBy() === column) {
      this.sortDir.set(this.sortDir() === 'asc' ? 'desc' : 'asc');
    } else {
      this.sortBy.set(column);
      this.sortDir.set('asc');
    }
  }

  /** Entry point from the round complete-toggle button. Opens a
   *  confirm dialog when the click is a mark-as-done (destructive-ish
   *  — completing fires the task.completed workflow which emails the
   *  assignee). Reopening a done task is silent — the action is safe
   *  and low-cost, no need to interrupt. */
  protected toggleComplete(task: Task, checked: boolean): void {
    if (this.togglingId()) return;
    if (checked) {
      this.completingTask.set(task);
      return;
    }
    this._applyComplete(task, false);
  }

  /** Called by the confirm dialog's Confirm button. */
  protected confirmCompleteRow(): void {
    const task = this.completingTask();
    if (!task) return;
    this.completingTask.set(null);
    this._applyComplete(task, true);
  }

  protected closeCompleteRow(): void {
    this.completingTask.set(null);
  }

  private _applyComplete(task: Task, checked: boolean): void {
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { status: checked ? 'done' : 'open' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
          if (checked) {
            this.toast.success('Task marked done.', { subtitle: task.title });
          } else {
            this.toast.info('Task reopened.', { subtitle: task.title });
          }
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          const msg = extractApiError(err) ?? 'Could not update the task.';
          this.toast.error('Could not update the task.', { subtitle: msg });
        },
      });
  }

  /** Dashboard deep links: `?new=1` opens Create, `?task=<id>` opens
   *  that task. Both params are stripped so a refresh doesn't reopen. */
  private openFromLink(isNew: boolean, taskId: string | null): void {
    if (!isNew && !taskId) return;
    if (isNew) {
      this.openCreate();
    } else if (taskId) {
      this.api
        .get(taskId)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (task) => this.openEdit(task),
          error: () =>
            this.toast.warn('Task not found', {
              subtitle: 'It may have been deleted or reassigned.',
            }),
        });
    }
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { new: null, task: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected openCreate(): void {
    this.editingTask.set(null);
    this.modalOpen.set(true);
  }

  protected openEdit(task: Task): void {
    this.editingTask.set(task);
    this.modalOpen.set(true);
  }

  protected closeModal(): void {
    this.modalOpen.set(false);
    this.editingTask.set(null);
  }

  protected onSaved(): void {
    const wasEdit = this.editingTask() !== null;
    this.closeModal();
    this.fetch();
    this.toast.success(wasEdit ? 'Task updated.' : 'Task created.', {
      subtitle: wasEdit ? 'Your changes are saved.' : 'The new task is on the list.',
    });
  }

  protected formatDue(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);
    const isTomorrow =
      d.getFullYear() === tomorrow.getFullYear() &&
      d.getMonth() === tomorrow.getMonth() &&
      d.getDate() === tomorrow.getDate();
    const time = d.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    });
    if (sameDay) return `Today, ${time}`;
    if (isTomorrow) return `Tomorrow, ${time}`;
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const isYesterday =
      d.getFullYear() === yesterday.getFullYear() &&
      d.getMonth() === yesterday.getMonth() &&
      d.getDate() === yesterday.getDate();
    if (isYesterday) return `Yesterday, ${time}`;
    const date = d.toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric',
    });
    return `${date}, ${time}`;
  }

  protected isOverdue(task: Task): boolean {
    if (!task.due_at || task.status !== 'open') return false;
    return new Date(task.due_at).getTime() < Date.now();
  }

  /** Open, not yet overdue, due later today. */
  protected isDueToday(task: Task): boolean {
    if (!task.due_at || task.status !== 'open' || this.isOverdue(task)) return false;
    return new Date(task.due_at).toDateString() === new Date().toDateString();
  }

  /** Colour for the due date: red overdue, amber due today, muted otherwise. */
  protected dueClass(task: Task): string {
    if (this.isOverdue(task)) return 'font-medium text-red-600 dark:text-red-400';
    if (this.isDueToday(task)) return 'font-medium text-amber-700 dark:text-amber-300';
    return 'text-muted';
  }

  protected assigneeName(task: Task): string {
    return this.assigneeMap().get(task.assigned_to_id) ?? '—';
  }

  /** T7 — Assignee dropdown hidden when the "Mine" chip is active
   *  (filtering "Mine" by owner=Other silently produces zero rows;
   *  hide the trap). */
  protected readonly showAssigneeDropdown = computed(
    () => this.canViewAll() && this.scope() !== 'mine',
  );

  // --- T1: mark missed ----------------------------------------------------

  /** Row-button click → open confirm dialog. The actual PATCH fires
   *  from `confirmMarkMissed` after the operator clicks through. */
  protected onMarkMissed(task: Task): void {
    if (this.togglingId()) return;
    if (task.status !== 'open') return;
    this.missingTask.set(task);
  }

  protected closeMarkMissed(): void {
    this.missingTask.set(null);
  }

  protected confirmMarkMissed(): void {
    const task = this.missingTask();
    if (!task) return;
    if (this.togglingId()) return;
    this.missingTask.set(null);
    this.togglingId.set(task.id);
    this.api
      .markMissed(task.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
          this.toast.success('Task marked missed.', { subtitle: task.title });
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          const msg = extractApiError(err) ?? 'Could not mark the task missed.';
          this.toast.error('Could not mark the task missed.', { subtitle: msg });
        },
      });
  }

  // --- T2: single-row delete ----------------------------------------------

  protected openDeleteRow(task: Task): void {
    this.deletingTask.set(task);
  }

  protected closeDeleteRow(): void {
    this.deletingTask.set(null);
    this.deleteSubmitting.set(false);
  }

  protected confirmDeleteRow(): void {
    const t = this.deletingTask();
    if (!t) return;
    this.deleteSubmitting.set(true);
    this.api
      .delete(t.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleteSubmitting.set(false);
          this.closeDeleteRow();
          this.state.items.update((rows) => rows.filter((r) => r.id !== t.id));
          this.state.total.update((n) => Math.max(0, n - 1));
          this.loadCounts();
          this.toast.success('Task deleted.', { subtitle: t.title });
        },
        error: (err: HttpErrorResponse) => {
          this.deleteSubmitting.set(false);
          const msg = extractApiError(err) ?? 'Could not delete the task.';
          this.toast.error('Could not delete the task.', { subtitle: msg });
        },
      });
  }

  // --- T9: snooze shortcuts ----------------------------------------------

  /** Row-button click → open the "Snooze +1 week" confirm dialog.
   *  The PATCH fires from `confirmSnoozeWeek` after the operator
   *  clicks through. */
  protected snoozeTask(task: Task, _deltaMinutes: number): void {
    if (this.togglingId()) return;
    // Signature kept `deltaMinutes` for template-call compatibility;
    // the +1-week row-button is currently the only caller and it
    // hard-codes 7 days. The confirm flow reproduces that delta.
    this.snoozingWeekTask.set(task);
  }

  protected closeSnoozeWeek(): void {
    this.snoozingWeekTask.set(null);
  }

  protected confirmSnoozeWeek(): void {
    const task = this.snoozingWeekTask();
    if (!task) return;
    if (this.togglingId()) return;
    this.snoozingWeekTask.set(null);
    const anchor = task.due_at ? new Date(task.due_at) : new Date();
    const next = new Date(anchor.getTime() + 7 * 24 * 60 * 60 * 1000);
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { due_at: next.toISOString() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
          this.toast.success('Task snoozed by 1 week.', { subtitle: task.title });
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          const msg = extractApiError(err) ?? 'Could not reschedule the task.';
          this.toast.error('Could not reschedule the task.', { subtitle: msg });
        },
      });
  }

  /** Row-button click → open the "Snooze to tomorrow 9am" confirm.
   *  Previously the button reassigned the due date on a single click
   *  with no undo. */
  protected snoozeToTomorrow(task: Task): void {
    if (this.togglingId()) return;
    this.snoozingTomorrowTask.set(task);
  }

  protected closeSnoozeTomorrow(): void {
    this.snoozingTomorrowTask.set(null);
  }

  protected confirmSnoozeTomorrow(): void {
    const task = this.snoozingTomorrowTask();
    if (!task) return;
    if (this.togglingId()) return;
    this.snoozingTomorrowTask.set(null);
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { due_at: tomorrow.toISOString() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
          this.toast.success('Task snoozed to tomorrow 9 AM.', { subtitle: task.title });
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          const msg = extractApiError(err) ?? 'Could not reschedule the task.';
          this.toast.error('Could not reschedule the task.', { subtitle: msg });
        },
      });
  }

  // --- T15: saved views --------------------------------------------------

  protected reloadSavedViews(): void {
    this.savedViewsApi
      .list('tasks')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.savedViews.set(rows),
        error: () => this.savedViews.set([]),
      });
  }

  /** Esc closes the save-view dialog, else the views menu. (The task
   *  form and confirm dialogs handle their own Esc.) */
  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.saveViewOpen()) this.closeSaveView();
    else if (this.viewsMenuOpen()) this.viewsMenuOpen.set(false);
  }

  protected toggleViewsMenu(): void {
    this.viewsMenuOpen.update((v) => !v);
  }

  protected applyView(v: SavedView): void {
    // Whitelist each field before writing it into a signal. A saved
    // view carries JSON from the DB — a stale schema, hand-crafted
    // API call, or future refactor could drop unexpected values in,
    // and the backend then 422s the next list call. Ignore unknowns.
    const cfg = (v.config ?? {}) as SavedViewConfig & {
      chip?: unknown;
      status?: unknown;
      due_filter?: unknown;
      priority?: unknown;
    };
    const savedScope = (cfg as { scope?: unknown }).scope;
    if (savedScope === 'all' || savedScope === 'mine') this.setScope(savedScope);
    if (typeof cfg.chip === 'string' && (CHIP_KEYS as readonly string[]).includes(cfg.chip)) {
      this.selectChip(cfg.chip as Chip);
    }
    if (
      cfg.status === 'open' ||
      cfg.status === 'done' ||
      cfg.status === 'cancelled' ||
      cfg.status === 'missed'
    ) {
      this.status.set(cfg.status);
    }
    if (
      cfg.due_filter === 'today' ||
      cfg.due_filter === 'overdue' ||
      cfg.due_filter === 'upcoming'
    ) {
      this.dueFilter.set(cfg.due_filter);
    }
    if (cfg.priority === 'low' || cfg.priority === 'med' || cfg.priority === 'high') {
      this.priorityFilter.set(cfg.priority);
    }
    if (
      cfg.sort === 'due_at' ||
      cfg.sort === 'priority' ||
      cfg.sort === 'title' ||
      cfg.sort === 'created_at' ||
      cfg.sort === 'last_activity_at'
    ) {
      this.sortBy.set(cfg.sort);
    }
    if (cfg.order === 'asc' || cfg.order === 'desc') {
      this.sortDir.set(cfg.order);
    }
    this.currentViewId.set(v.id);
    this.currentViewName.set(v.name);
    this.viewsMenuOpen.set(false);
  }

  protected openSaveView(): void {
    this.saveViewName.setValue('');
    this.saveViewShared.set(false);
    this.saveViewOpen.set(true);
  }

  protected closeSaveView(): void {
    this.saveViewOpen.set(false);
  }

  protected submitSaveView(): void {
    const name = this.saveViewName.value.trim();
    if (!name) return;
    const cfg: SavedViewConfig & Record<string, unknown> = {
      sort: this.sortBy(),
      order: this.sortDir(),
    };
    cfg['chip'] = this.activeChip();
    cfg['scope'] = this.scope();
    cfg['status'] = this.status();
    cfg['due_filter'] = this.dueFilter() ?? null;
    cfg['priority'] = this.priorityFilter() ?? null;
    this.savedViewsApi
      .create({
        entity: 'tasks',
        name,
        config: cfg,
        shared: this.saveViewShared(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (v) => {
          this.savedViews.update((prev) => [...prev, v]);
          this.currentViewId.set(v.id);
          this.currentViewName.set(v.name);
          this.saveViewOpen.set(false);
          this.toast.success('View saved', { subtitle: v.name });
        },
        error: (err: HttpErrorResponse) => {
          this.toast.error('Could not save the view', {
            subtitle: extractApiError(err) ?? undefined,
          });
        },
      });
  }

  protected async deleteCurrentView(): Promise<void> {
    const id = this.currentViewId();
    if (!id) return;
    const ok = await this.confirmDialog.ask({
      title: `Delete the view “${this.currentViewName() ?? ''}”?`,
      body: 'Anyone it was shared with loses it too. Your tasks are not affected.',
      confirmLabel: 'Delete view',
      danger: true,
    });
    if (!ok) return;
    this.savedViewsApi
      .delete(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.savedViews.update((rows) => rows.filter((r) => r.id !== id));
          this.currentViewId.set(null);
          this.currentViewName.set(null);
          this.toast.success('View deleted');
        },
        error: (err: HttpErrorResponse) =>
          this.toast.error('Could not delete the view', {
            subtitle: extractApiError(err) ?? undefined,
          }),
      });
  }

  protected priorityClass(p: TaskPriority): string {
    switch (p) {
      case 'high':
        return 'bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300';
      case 'med':
        return 'bg-amber-500/10 text-amber-700 ring-amber-500/20 dark:text-amber-300';
      default:
        return 'bg-surface-2 text-muted ring-subtle';
    }
  }

  /** Monotonic request id — bumped on every `fetch()`, checked in the
   *  response callback so a slow earlier response can't overwrite a
   *  faster later one when the user clicks chips rapidly. */
  private fetchSeq = 0;

  private fetch(): void {
    const seq = ++this.fetchSeq;
    this.page.set(1);
    this.loadingMore.set(false);
    this.state.loading.set(true);
    this.state.loadError.set(null);
    this.loadCounts();

    const obs = this.listRequest(1);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res: TaskListResponse) => {
        if (seq !== this.fetchSeq) return;
        this.state.items.set(res.items);
        this.state.total.set(res.total);
        this.state.loading.set(false);
        // If the edit modal is open on a task that just got refreshed
        // (e.g. inline snooze/mark-missed while the modal is up, or a
        // row action fired between "click +1w" and "click title"),
        // re-seed `editingTask` with the fresh row so the modal's due
        // / status / assignee reflect the latest server state instead
        // of the click-time snapshot.
        const editing = this.editingTask();
        if (editing) {
          const refreshed = res.items.find((r) => r.id === editing.id);
          if (refreshed && refreshed !== editing) {
            this.editingTask.set(refreshed);
          }
        }
      },
      error: (err: HttpErrorResponse) => {
        if (seq !== this.fetchSeq) return;
        this.state.items.set([]);
        this.state.total.set(0);
        this.state.loading.set(false);
        this.state.loadError.set(extractApiError(err) ?? 'Could not load tasks.');
      },
    });
  }

  private taskCount(n: number): string {
    return `${n} task${n === 1 ? '' : 's'}`;
  }

  /** Count badge colour on a status chip — red for a non-zero Overdue. */
  protected chipCountClass(c: ChipDef, n: TaskCounts): string {
    if (this.activeChip() === c.key) return 'opacity-80';
    if (c.key === 'overdue' && n.overdue > 0) return 'text-red-600 dark:text-red-400';
    return 'text-faint';
  }

  protected retry(): void {
    this.fetch();
  }

  /** List request for the current filters at a given page. */
  private listRequest(page: number) {
    const filters: TaskListFilters = {
      status: this.status(),
      priority: this.priorityFilter(),
      q: this.q() || undefined,
      due_filter: this.dueFilter(),
      sort_by: this.sortBy(),
      sort_dir: this.sortDir(),
      assigned_to_id: this.resolveAssignee(),
      page,
      size: PAGE_SIZE,
    };
    return this.scope() === 'all' ? this.api.listAll(filters) : this.api.listMine(filters);
  }

  protected loadMore(): void {
    if (this.loadingMore() || !this.hasMore()) return;
    const seq = this.fetchSeq;
    const next = this.page() + 1;
    this.loadingMore.set(true);
    this.listRequest(next)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res: TaskListResponse) => {
          if (seq !== this.fetchSeq) return;
          // De-dupe — a row changed since page 1 can shift server offsets.
          const seen = new Set(this.state.items().map((t) => t.id));
          this.state.items.update((cur) => [...cur, ...res.items.filter((t) => !seen.has(t.id))]);
          this.state.total.set(res.total);
          this.page.set(next);
          this.loadingMore.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.fetchSeq) return;
          this.loadingMore.set(false);
          this.toast.error('Could not load more tasks', {
            subtitle: extractApiError(err) ?? undefined,
          });
        },
      });
  }

  /** Header counts for the scope being viewed (and owner, on "All"). */
  private loadCounts(): void {
    const obs =
      this.scope() === 'all' ? this.api.countsAll(this.resolveAssignee()) : this.api.countsMine();
    obs
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (c) => this.counts.set(c), error: () => this.counts.set(null) });
  }

  /** Router link for a task's linked record, or null when it has none. */
  protected relatedLink(t: Task): string[] | null {
    if (!t.related_entity_id) return null;
    if (t.related_entity_type === 'contact') return ['/user/contacts', t.related_entity_id];
    if (t.related_entity_type === 'lead') return ['/user/leads', t.related_entity_id];
    return null;
  }

  private loadAssignees(): void {
    this.http
      .get<TaskAssignee[]>(`${environment.apiBaseUrl}/users`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.assignees.set(rows),
        // The modal handles an empty assignee list (hides the dropdown
        // and defaults to the caller), but a silent 401/403/500 leaves
        // every row's Owner column rendering "—" and admins have no
        // way to reassign — surface via console.warn so the failure
        // is attributable when troubleshooting.
        error: (err: HttpErrorResponse) => {
          console.warn('[tasks] assignees load failed', err.status, err.message);
          this.assignees.set([]);
        },
      });
  }

  // --- Selection (Step 2) ------------------------------------------------

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

  // --- Bulk handlers (Step 2) -------------------------------------------

  protected onBulkAction(key: string): void {
    this.state.bulkError.set(null);
    if (key === 'reassign') this.state.bulkModal.set('reassign');
    else if (key === 'done') this.state.bulkModal.set('done');
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
    if (!payload.userId) {
      this.state.bulkError.set('Tasks require an owner — pick a user.');
      return;
    }
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.toast.success(`Reassigned ${this.taskCount(ids.length)}`, {
            subtitle: `Now assigned to ${this.assigneeMap().get(payload.userId ?? '') ?? 'the new owner'}.`,
          });
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not reassign tasks.');
        },
      });
  }

  protected onBulkMarkDone(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkMarkDone(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          if (result.skipped === 0) {
            this.toast.success(`Marked ${this.taskCount(result.done)} done`);
          } else {
            this.toast.warn(`${result.done} marked done`, {
              subtitle: `${result.skipped} skipped — already done.`,
            });
          }
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not mark tasks done.');
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
          this.toast.success(`Deleted ${this.taskCount(ids.length)}`);
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not delete tasks.');
        },
      });
  }

  /** Resolve the assignee dropdown value into the backend's
   * `assigned_to_id` query param. `''` → undefined; `'me'` → current
   * user; UUID → that UUID. */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.callerUuid() ?? undefined;
    return raw;
  }
}
