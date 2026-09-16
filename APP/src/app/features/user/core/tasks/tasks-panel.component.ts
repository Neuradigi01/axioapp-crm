import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { commonValidators } from '../shared/validators';
import { TaskAssignee, TaskFormModalComponent } from './task-form-modal.component';
import { Task, TaskPriority, TasksApiService } from './tasks-api.service';
import { extractApiError } from '@core/services/api-error.util';

/** Priority picker options for the inline add-task form. Same three
 *  values the backend enum accepts; label-cased for display. */
const PRIORITY_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'low', label: 'Low' },
  { value: 'med', label: 'Medium' },
  { value: 'high', label: 'High' },
];

/**
 * Tasks panel rendered inside any entity detail page. Inputs are
 * `(entityType, entityId)` only — no contact-specific code lives here,
 * so the same component plugs into Leads (2.12) and Walk-ins later.
 *
 * Behaviour:
 *   - Lists tasks for the given entity, earliest-due first.
 *   - Inline "Add task" form (title, due, priority).
 *   - Click the checkbox to flip status open ↔ done. Strikethrough on done.
 *   - Optimistic UI: server-confirmed updates replace the in-memory row.
 */
@Component({
  selector: 'app-tasks-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    TaskFormModalComponent,
    MobileDateTimeComponent,
    MobileSelectComponent,
  ],
  templateUrl: './tasks-panel.component.html',
})
export class TasksPanelComponent {
  private readonly api = inject(TasksApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly confirmDialog = inject(ConfirmDialogService);
  /** Zoneless: HTTP subscribe callbacks fire outside any tracked
   *  execution context; signal writes should schedule CD on their own
   *  but explicit `markForCheck()` is belt-and-braces after every async
   *  state mutation. Same pattern as the sibling `LeadFollowUpsPanel`. */
  private readonly cdr = inject(ChangeDetectorRef);

  // T6 — Edit + delete on the panel. Edit reuses the shared
  // TaskFormModal; delete goes through the app-wide confirm dialog
  // so the destructive prompt matches the rest of the UI.
  protected readonly editingTask = signal<Task | null>(null);
  protected readonly callerUuid = signal<string | null>(null);
  /** Populated on mount from the session-cached UsersDirectoryService.
   *  Feeds the panel-hosted edit modal's assignee picker — without it
   *  the picker renders as empty and an Admin editing a task from a
   *  contact / lead / walk-in detail page has no way to reassign. */
  protected readonly assignees = signal<TaskAssignee[]>([]);
  /** Mirrors the main tasks-page permission check. Passed through to
   *  the modal so a rep without `tasks.assign_others` sees no picker
   *  (edits still work for their own tasks). */
  protected readonly canAssignOthers = this.auth.hasPermission('tasks.assign_others');
  /** Row delete is Owner/Admin-only — same gate as the standalone
   *  Tasks page. Hides the trash icon for Employee / Sales Manager /
   *  Support Agent, whose backend call would 403 anyway. */
  protected readonly canDelete = this.auth.hasPermission('tasks.delete');

  readonly entityType = input.required<string>();
  readonly entityId = input.required<string>();

  /** Emits after the inline add-task form successfully creates a row.
   *  Lets an entity-detail parent (e.g. lead-detail) refresh a sibling
   *  view that also lists these rows — the lead-detail Overview tab's
   *  Follow-Up Status panel is a separate `LeadFollowUpsPanel` instance
   *  and would otherwise stay stale until the user clicks Refresh. */
  readonly created = output<Task>();

  protected readonly items = signal<Task[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly submitting = signal(false);
  protected readonly addError = signal<string | null>(null);

  protected readonly form = this.fb.group({
    title: ['', [Validators.required, Validators.maxLength(255)]],
    // Quick-add task: due date is optional but if set must not be in
    // the past. Today is a legitimate pick ("do this today").
    due_at: ['', [commonValidators.dateNotPast]],
    priority: this.fb.control<TaskPriority>('med', { nonNullable: true }),
  });

  protected readonly priorityOptions = PRIORITY_OPTIONS;
  /** `min` bound for the datetime picker so the calendar disables past
   *  days at open-time — mirrors the `dateNotPast` validator on the
   *  form control, which is authoritative. Recomputed each time the
   *  panel is instantiated (constructor scope) which is good enough
   *  for a form the user typically submits in a few seconds. */
  protected readonly dueMin = this._todayLocalInput();

  protected readonly openCount = computed(
    () => this.items().filter((t) => t.status === 'open').length,
  );
  protected readonly doneCount = computed(
    () => this.items().filter((t) => t.status === 'done').length,
  );
  protected readonly skeletonRows = [0, 1] as const;

  constructor() {
    // Cache caller UUID for the edit-modal (used as the fallback
    // assignee). Silently no-op if /me isn't accessible.
    this.callerUuid.set(this.auth.currentUserId());
    // Load assignees once via the shared directory service — cached
    // per session so opening the panel on multiple detail pages
    // doesn't re-fetch. Only needed when the caller can reassign.
    if (this.canAssignOthers) {
      this.usersDir
        .list()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (rows) =>
            this.assignees.set(
              rows.map((u) => ({ id: u.id, full_name: u.full_name, email: u.email })),
            ),
          error: (err: HttpErrorResponse) => {
            // Fall back to an empty list — the modal handles that by
            // hiding the picker — but log so the failure isn't
            // invisible when an Admin can't figure out why they
            // suddenly can't reassign.
            console.warn('[tasks-panel] assignees load failed', err.status, err.message);
            this.assignees.set([]);
          },
        });
    }
    effect(() => {
      const eType = this.entityType();
      const eId = this.entityId();
      if (!eType || !eId) return;
      this.reload();
    });
  }

  // T6 — Edit + delete row actions.

  protected openEdit(task: Task): void {
    this.editingTask.set(task);
  }

  protected closeEdit(): void {
    this.editingTask.set(null);
  }

  protected onEditSaved(updated: Task): void {
    this.editingTask.set(null);
    this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
  }

  protected async onDelete(task: Task): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: `Delete task “${task.title}”?`,
      body: 'This will remove the task for everyone assigned to it. This cannot be undone.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.api
      .delete(task.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.items.update((rows) => rows.filter((r) => r.id !== task.id));
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not delete the task.');
          this.cdr.markForCheck();
        },
      });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listForEntity(this.entityType(), this.entityId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loadError.set(extractApiError(err) ?? 'Could not load tasks.');
          this.loading.set(false);
          this.cdr.markForCheck();
        },
      });
  }

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const title = (v.title ?? '').trim();
    if (title.length === 0) return;
    this.submitting.set(true);
    this.addError.set(null);
    this.api
      .create({
        title,
        related_entity_type: this.entityType(),
        related_entity_id: this.entityId(),
        priority: v.priority,
        due_at: this.normalizeDue(v.due_at),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (task) => {
          this.submitting.set(false);
          this.form.reset({ title: '', due_at: '', priority: 'med' });
          // Re-fetch instead of locally inserting so server-side
          // due_at ordering stays consistent without us re-sorting.
          this.items.update((rows) => [task, ...rows].sort(this.compareTasks));
          this.cdr.markForCheck();
          this.created.emit(task);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.addError.set(extractApiError(err) ?? 'Could not create task.');
          this.cdr.markForCheck();
        },
      });
  }

  protected toggleDone(task: Task): void {
    const nextStatus = task.status === 'done' ? 'open' : 'done';
    // Optimistic local flip — reverts on error.
    const before = this.items();
    this.items.update((rows) =>
      rows.map((r) => (r.id === task.id ? { ...r, status: nextStatus } : r)),
    );
    this.api
      .update(task.id, { status: nextStatus })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.cdr.markForCheck();
        },
        error: (err: HttpErrorResponse) => {
          this.items.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not update task.');
          this.cdr.markForCheck();
        },
      });
  }

  protected priorityRing(p: TaskPriority): string {
    switch (p) {
      case 'high':
        return 'bg-red-100 text-red-700 ring-red-200';
      case 'med':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'low':
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  protected formatDue(iso: string | null): string {
    if (iso === null) return 'No due date';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'No due date';
    return d.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected isOverdue(task: Task): boolean {
    if (task.status !== 'open' || task.due_at === null) return false;
    return new Date(task.due_at).getTime() < Date.now();
  }

  private normalizeDue(value: string | null | undefined): string | null {
    if (!value) return null;
    // `crm-mobile-datetime` emits "YYYY-MM-DDTHH:mm" (same shape as
    // native <input type="datetime-local">) — convert to ISO for the
    // backend, which stores every timestamp as UTC.
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString();
  }

  /** Today at 00:00 in local wall-clock time, in the
   *  `YYYY-MM-DDTHH:mm` shape `crm-mobile-datetime` uses for its
   *  `[min]` bound. Prevents the calendar from letting the rep pick a
   *  day earlier than today — matches `commonValidators.dateNotPast`. */
  private _todayLocalInput(): string {
    const d = new Date();
    const pad = (n: number): string => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T00:00`;
  }

  private compareTasks(a: Task, b: Task): number {
    // Earliest due_at first; nulls (no due) last; tie-break on created_at desc.
    if (a.due_at && b.due_at) {
      return a.due_at < b.due_at ? -1 : a.due_at > b.due_at ? 1 : 0;
    }
    if (a.due_at && !b.due_at) return -1;
    if (!a.due_at && b.due_at) return 1;
    return a.created_at < b.created_at ? 1 : -1;
  }
}
