import { CommonModule } from '@angular/common';
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
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { environment } from '../../../../../environments/environment';
import { FurnitureAuthService } from '../auth/auth.service';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
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
  Task,
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
type Chip = 'all' | 'mine' | 'overdue' | 'today' | 'done';

interface ChipDef {
  key: Chip;
  label: string;
  scopeForce?: Scope;
}

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
  ],
  providers: [TasksListState],
  templateUrl: './tasks.page.html',
})
export class TasksPageComponent {
  private readonly api = inject(TasksApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  protected readonly state = inject(TasksListState);

  protected readonly canViewAll = signal(false);
  protected readonly callerUuid = signal<string | null>(null);

  protected readonly assignees = signal<TaskAssignee[]>([]);
  protected readonly assigneeMap = computed(() => {
    const m = new Map<string, string>();
    for (const a of this.assignees()) m.set(a.id, a.full_name || a.email);
    return m;
  });

  protected readonly activeChip = signal<Chip>('mine');
  protected readonly scope = signal<Scope>('mine');
  protected readonly status = signal<TaskListFilters['status']>('open');
  protected readonly dueFilter = signal<TaskDueFilter | undefined>(undefined);
  protected readonly priorityFilter = signal<TaskPriority | undefined>(undefined);
  protected readonly q = signal<string>('');
  protected readonly sortBy = signal<TaskSortBy>('due_at');
  protected readonly sortDir = signal<TaskSortDir>('asc');

  protected readonly searchCtrl = new FormControl('', { nonNullable: true });
  protected readonly chipBusy = signal<Chip | null>(null);
  protected readonly togglingId = signal<string | null>(null);

  protected readonly modalOpen = signal(false);
  protected readonly editingTask = signal<Task | null>(null);

  // T2 — single-row delete confirmation.
  protected readonly deletingTask = signal<Task | null>(null);
  protected readonly deleteSubmitting = signal(false);

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

  // --- URL state (Step 2) ------------------------------------------------

  readonly urlState: UrlFilterStateConfig = {
    chip: {
      read: () => this.activeChip(),
      write: (v) => {
        if (v === 'all' || v === 'mine' || v === 'overdue' || v === 'today' || v === 'done') {
          this.selectChip(v);
        }
      },
      queryKey: 'chip',
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

  protected readonly chips = computed<ChipDef[]>(() => {
    const base: ChipDef[] = [];
    if (this.canViewAll()) {
      base.push({ key: 'all', label: 'All', scopeForce: 'all' });
    }
    base.push({ key: 'mine', label: 'Mine', scopeForce: 'mine' });
    base.push({ key: 'overdue', label: 'Overdue' });
    base.push({ key: 'today', label: 'Due today' });
    base.push({ key: 'done', label: 'Done' });
    return base;
  });

  /** Headline counters — recomputed from the items signal so they
   *  reflect whatever the current filter is showing. For richer counts
   *  ("3 open across the whole org") we'd need extra endpoints. */
  protected readonly headlineCounts = computed(() => {
    const now = Date.now();
    const startToday = new Date();
    startToday.setHours(0, 0, 0, 0);
    const endToday = new Date();
    endToday.setHours(23, 59, 59, 999);

    let open = 0;
    let overdue = 0;
    let dueToday = 0;
    for (const t of this.state.items()) {
      if (t.status === 'open') open += 1;
      if (t.due_at) {
        const due = new Date(t.due_at).getTime();
        if (t.status === 'open' && due < now) overdue += 1;
        if (t.status === 'open' && due >= startToday.getTime() && due <= endToday.getTime()) {
          dueToday += 1;
        }
      }
    }
    return { open, overdue, dueToday };
  });

  constructor() {
    this.state.bulkActions.set([
      { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'tasks.write' },
      { key: 'done', label: 'Mark done', icon: 'check-circle-2', permissionKey: 'tasks.write' },
      {
        key: 'delete',
        label: 'Delete',
        icon: 'trash-2',
        danger: true,
        permissionKey: 'tasks.write',
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
          this.callerUuid.set(me.id);
          this.activeChip.set(canView ? 'all' : 'mine');
          this.scope.set(canView ? 'all' : 'mine');
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
    if (this.chipBusy()) return;
    this.chipBusy.set(chip);
    this.activeChip.set(chip);

    switch (chip) {
      case 'all':
        this.scope.set('all');
        this.status.set('open');
        this.dueFilter.set(undefined);
        break;
      case 'mine':
        this.scope.set('mine');
        this.status.set('open');
        this.dueFilter.set(undefined);
        break;
      case 'overdue':
        // scope preserved
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
    }
  }

  protected setSort(column: TaskSortBy): void {
    if (this.sortBy() === column) {
      this.sortDir.set(this.sortDir() === 'asc' ? 'desc' : 'asc');
    } else {
      this.sortBy.set(column);
      this.sortDir.set('asc');
    }
  }

  protected toggleComplete(task: Task, checked: boolean): void {
    if (this.togglingId()) return;
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { status: checked ? 'done' : 'open' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          this.state.loadError.set(extractApiError(err) ?? 'Could not update the task.');
        },
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
    this.closeModal();
    this.fetch();
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
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric',
    });
  }

  protected isOverdue(task: Task): boolean {
    if (!task.due_at || task.status !== 'open') return false;
    return new Date(task.due_at).getTime() < Date.now();
  }

  protected assigneeName(task: Task): string {
    if (this.callerUuid() && task.assigned_to_id === this.callerUuid()) {
      return 'You';
    }
    return this.assigneeMap().get(task.assigned_to_id) ?? '—';
  }

  /** T7 — Assignee dropdown hidden when the "Mine" chip is active
   *  (filtering "Mine" by owner=Other silently produces zero rows;
   *  hide the trap). */
  protected readonly showAssigneeDropdown = computed(
    () => this.canViewAll() && this.scope() !== 'mine',
  );

  // --- T1: mark missed ----------------------------------------------------

  protected onMarkMissed(task: Task): void {
    if (this.togglingId()) return;
    if (task.status !== 'open') return;
    this.togglingId.set(task.id);
    this.api
      .markMissed(task.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          this.state.loadError.set(extractApiError(err) ?? 'Could not mark the task missed.');
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
        },
        error: (err: HttpErrorResponse) => {
          this.deleteSubmitting.set(false);
          this.state.loadError.set(extractApiError(err) ?? 'Could not delete the task.');
        },
      });
  }

  // --- T9: snooze shortcuts ----------------------------------------------

  /** Reschedule the task's due_at by the given delta (positive minutes
   *  advance the due, negative rewind). Anchored on the existing due
   *  if set, otherwise on "now" (typical for tasks with no due yet
   *  where the operator hits "+1d" to give it one). Fires a PATCH
   *  and re-fetches on success. */
  protected snoozeTask(task: Task, deltaMinutes: number): void {
    if (this.togglingId()) return;
    const anchor = task.due_at ? new Date(task.due_at) : new Date();
    const next = new Date(anchor.getTime() + deltaMinutes * 60 * 1000);
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { due_at: next.toISOString() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          this.state.loadError.set(extractApiError(err) ?? 'Could not reschedule the task.');
        },
      });
  }

  /** Convenience: bump the due to tomorrow 9am (matches how most
   *  Todoist-style CRMs interpret "Tomorrow"). */
  protected snoozeToTomorrow(task: Task): void {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    if (this.togglingId()) return;
    this.togglingId.set(task.id);
    this.api
      .update(task.id, { due_at: tomorrow.toISOString() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.togglingId.set(null);
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.togglingId.set(null);
          this.state.loadError.set(extractApiError(err) ?? 'Could not reschedule the task.');
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

  protected toggleViewsMenu(): void {
    this.viewsMenuOpen.update((v) => !v);
  }

  protected applyView(v: SavedView): void {
    const cfg = (v.config ?? {}) as SavedViewConfig & {
      chip?: Chip;
      status?: Task['status'];
      due_filter?: TaskDueFilter;
      priority?: TaskPriority;
    };
    if (cfg.chip) this.selectChip(cfg.chip);
    if (cfg.status) this.status.set(cfg.status);
    if (cfg.due_filter) this.dueFilter.set(cfg.due_filter);
    if (cfg.priority) this.priorityFilter.set(cfg.priority);
    if (cfg.sort) this.sortBy.set(cfg.sort as TaskSortBy);
    if (cfg.order) this.sortDir.set(cfg.order);
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
        },
        error: (err: HttpErrorResponse) => {
          this.state.loadError.set(extractApiError(err) ?? 'Could not save view.');
        },
      });
  }

  protected deleteCurrentView(): void {
    const id = this.currentViewId();
    if (!id) return;
    if (!confirm('Delete this saved view?')) return;
    this.savedViewsApi
      .delete(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.savedViews.update((rows) => rows.filter((r) => r.id !== id));
          this.currentViewId.set(null);
          this.currentViewName.set(null);
        },
        error: () => undefined,
      });
  }

  protected priorityClass(p: TaskPriority): string {
    switch (p) {
      case 'high':
        return 'bg-red-500/10 text-red-400 ring-red-500/20';
      case 'med':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  private fetch(): void {
    this.state.loading.set(true);
    this.state.loadError.set(null);

    const filters: TaskListFilters = {
      status: this.status(),
      priority: this.priorityFilter(),
      q: this.q() || undefined,
      due_filter: this.dueFilter(),
      sort_by: this.sortBy(),
      sort_dir: this.sortDir(),
      assigned_to_id: this.resolveAssignee(),
      size: 100,
    };

    const obs = this.scope() === 'all' ? this.api.listAll(filters) : this.api.listMine(filters);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res: TaskListResponse) => {
        this.state.items.set(res.items);
        this.state.total.set(res.total);
        this.state.loading.set(false);
        this.chipBusy.set(null);
      },
      error: (err: HttpErrorResponse) => {
        this.state.items.set([]);
        this.state.total.set(0);
        this.state.loading.set(false);
        this.chipBusy.set(null);
        this.state.loadError.set(extractApiError(err) ?? 'Could not load tasks.');
      },
    });
  }

  private loadAssignees(): void {
    this.http
      .get<TaskAssignee[]>(`${environment.apiBaseUrl}/users`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.assignees.set(rows),
        // Silent fallback — the modal handles an empty assignee list
        // (it hides the dropdown and defaults to the caller).
        error: () => this.assignees.set([]),
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
          if (result.skipped > 0) {
            this.state.loadError.set(
              `${result.done} marked done; ${result.skipped} skipped (already done).`,
            );
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
