import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { TaskAssignee, TaskFormModalComponent } from './task-form-modal.component';
import { Task, TaskPriority, TasksApiService } from './tasks-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Tasks panel rendered inside any entity detail page. Inputs are
 * `(entityType, entityId)` only â€” no contact-specific code lives here,
 * so the same component plugs into Leads (2.12) and Walk-ins later.
 *
 * Behaviour:
 *   - Lists tasks for the given entity, earliest-due first.
 *   - Inline "Add task" form (title, due, priority).
 *   - Click the checkbox to flip status open â†” done. Strikethrough on done.
 *   - Optimistic UI: server-confirmed updates replace the in-memory row.
 */
@Component({
  selector: 'app-tasks-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, TaskFormModalComponent],
  templateUrl: './tasks-panel.component.html',
})
export class TasksPanelComponent {
  private readonly api = inject(TasksApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);

  // T6 — Edit + delete on the panel. Edit reuses the shared
  // TaskFormModal; delete uses a native confirm to stay lightweight.
  protected readonly editingTask = signal<Task | null>(null);
  protected readonly callerUuid = signal<string | null>(null);
  protected readonly assignees = signal<TaskAssignee[]>([]);

  readonly entityType = input.required<string>();
  readonly entityId = input.required<string>();

  protected readonly items = signal<Task[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly submitting = signal(false);
  protected readonly addError = signal<string | null>(null);

  protected readonly form = this.fb.group({
    title: ['', [Validators.required, Validators.maxLength(255)]],
    due_at: [''],
    priority: this.fb.control<TaskPriority>('med', { nonNullable: true }),
  });

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

  protected onDelete(task: Task): void {
    if (!confirm(`Delete task “${task.title}”?`)) return;
    this.api
      .delete(task.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.items.update((rows) => rows.filter((r) => r.id !== task.id));
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not delete the task.');
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
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loadError.set(extractApiError(err) ?? 'Could not load tasks.');
          this.loading.set(false);
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
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.addError.set(extractApiError(err) ?? 'Could not create task.');
        },
      });
  }

  protected toggleDone(task: Task): void {
    const nextStatus = task.status === 'done' ? 'open' : 'done';
    // Optimistic local flip â€” reverts on error.
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
        },
        error: (err: HttpErrorResponse) => {
          this.items.set(before);
          this.loadError.set(extractApiError(err) ?? 'Could not update task.');
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
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
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
    // <input type="datetime-local"> emits "YYYY-MM-DDTHH:mm" â€” convert to ISO.
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString();
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
