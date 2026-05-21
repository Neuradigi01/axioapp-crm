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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { environment } from '../../../../../environments/environment';
import { FurnitureAuthService } from '../auth/auth.service';
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
  imports: [CommonModule, ReactiveFormsModule, TaskFormModalComponent],
  templateUrl: './tasks.page.html',
})
export class TasksPageComponent {
  private readonly api = inject(TasksApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);

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
}
