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
import {
  BulkAction,
  BulkActionBarComponent,
} from '../shared/bulk-action-bar/bulk-action-bar.component';
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
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { extractApiError } from '@core/services/api-error.util';

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
import {
  TaskAssignee,
  TaskFormModalComponent,
} from './task-form-modal.component';

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
  templateUrl: './tasks.page.html',
})
export class TasksPageComponent {
  private readonly api = inject(TasksApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  protected readonly items = signal<Task[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
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

  // --- Assignee dropdown (Step 2) ----------------------------------------

  /** Owner filter — `'' | 'me' | <uuid>`. Orthogonal to chips: chips set
   * scope (mine vs all + status/due), this narrows whatever scope is
   * showing to one user. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** Directory of org users for the dropdown. Cached by `UsersDirectoryService`,
   * so this is cheap to read across the page. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  // --- Selection + bulk (Step 2) -----------------------------------------

  readonly selectedIds = signal<Set<string>>(new Set());
  readonly selectedCount = computed(() => this.selectedIds().size);

  readonly bulkActions = computed<BulkAction[]>(() => [
    { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'tasks.write' },
    { key: 'done', label: 'Mark done', icon: 'check-circle-2', permissionKey: 'tasks.write' },
    { key: 'delete', label: 'Delete', icon: 'trash-2', danger: true, permissionKey: 'tasks.write' },
  ]);

  readonly bulkModal = signal<'reassign' | 'done' | 'delete' | null>(null);
  readonly bulkSubmitting = signal(false);
  readonly bulkError = signal<string | null>(null);

  // --- URL state (Step 2) ------------------------------------------------

  readonly urlState: UrlFilterStateConfig = {
    chip: {
      read: () => this.activeChip(),
      write: (v) => {
        if (
          v === 'all' ||
          v === 'mine' ||
          v === 'overdue' ||
          v === 'today' ||
          v === 'done'
        ) {
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
    for (const t of this.items()) {
      if (t.status === 'open') open += 1;
      if (t.due_at) {
        const due = new Date(t.due_at).getTime();
        if (t.status === 'open' && due < now) overdue += 1;
        if (
          t.status === 'open' &&
          due >= startToday.getTime() &&
          due <= endToday.getTime()
        ) {
          dueToday += 1;
        }
      }
    }
    return { open, overdue, dueToday };
  });

  constructor() {
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
        },
        error: () => {
          this.loadError.set('Could not load your profile.');
        },
      });

    this.searchCtrl.valueChanges
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
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
          this.loadError.set(
            extractApiError(err) ?? 'Could not update the task.',
          );
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

  protected priorityClass(p: TaskPriority): string {
    switch (p) {
      case 'high':
        return 'bg-rose-50 text-rose-700 ring-rose-200';
      case 'med':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  private fetch(): void {
    this.loading.set(true);
    this.loadError.set(null);

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

    const obs =
      this.scope() === 'all'
        ? this.api.listAll(filters)
        : this.api.listMine(filters);

    obs
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res: TaskListResponse) => {
          this.items.set(res.items);
          this.total.set(res.total);
          this.loading.set(false);
          this.chipBusy.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.chipBusy.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not load tasks.');
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
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  protected clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  // --- Bulk handlers (Step 2) -------------------------------------------

  protected onBulkAction(key: string): void {
    this.bulkError.set(null);
    if (key === 'reassign') this.bulkModal.set('reassign');
    else if (key === 'done') this.bulkModal.set('done');
    else if (key === 'delete') this.bulkModal.set('delete');
  }

  protected closeBulkModal(): void {
    this.bulkModal.set(null);
    this.bulkSubmitting.set(false);
    this.bulkError.set(null);
  }

  protected onBulkReassign(payload: ReassignConfirm): void {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    if (!payload.userId) {
      this.bulkError.set('Tasks require an owner — pick a user.');
      return;
    }
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(extractApiError(err) ?? 'Could not reassign tasks.');
        },
      });
  }

  protected onBulkMarkDone(): void {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkMarkDone(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          if (result.skipped > 0) {
            this.loadError.set(
              `${result.done} marked done; ${result.skipped} skipped (already done).`,
            );
          }
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(
            extractApiError(err) ?? 'Could not mark tasks done.',
          );
        },
      });
  }

  protected onBulkDelete(): void {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkDelete(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(extractApiError(err) ?? 'Could not delete tasks.');
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
