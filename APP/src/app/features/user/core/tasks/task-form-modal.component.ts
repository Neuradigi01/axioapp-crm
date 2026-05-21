import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';

import { extractApiError } from '@core/services/api-error.util';

import {
  Task,
  TaskCreate,
  TaskPriority,
  TaskUpdate,
  TasksApiService,
} from './tasks-api.service';

export interface TaskAssignee {
  id: string;
  full_name: string;
  email: string;
}

/**
 * Create-or-edit task modal. Same form for both flows; `task` input
 * decides mode. Assignee dropdown comes from the parent (it knows
 * whether the caller has `users.read` to load the full list, or
 * should default to self only).
 */
@Component({
  selector: 'app-task-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './task-form-modal.component.html',
})
export class TaskFormModalComponent {
  private readonly api = inject(TasksApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  /** When set, the modal is in edit mode for this task. */
  @Input() task: Task | null = null;
  /** Active org members the user can be assigned to. Empty list means
   *  the caller can't load /users (no users.read); the assignee field
   *  is then hidden and we default to the caller's own id. */
  @Input() assignees: TaskAssignee[] = [];
  /** Caller's own UUID — used as the implicit assignee when the
   *  dropdown is hidden. */
  @Input() callerUuid: string | null = null;

  @Output() readonly saved = new EventEmitter<Task>();
  @Output() readonly cancelled = new EventEmitter<void>();

  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    title: ['', [Validators.required, Validators.maxLength(255)]],
    description: [''],
    due_at: [''],
    priority: ['med' as TaskPriority, Validators.required],
    assigned_to_id: [''],
  });

  protected readonly hasAssigneeDropdown = computed(
    () => this.assignees.length > 0,
  );

  protected readonly isEdit = computed(() => this.task !== null);

  ngOnChanges(): void {
    if (this.task) {
      // datetime-local needs `YYYY-MM-DDTHH:mm` — strip seconds / Z.
      const dueLocal = this.task.due_at
        ? new Date(this.task.due_at).toISOString().slice(0, 16)
        : '';
      this.form.reset({
        title: this.task.title,
        description: this.task.description ?? '',
        due_at: dueLocal,
        priority: this.task.priority,
        assigned_to_id: this.task.assigned_to_id,
      });
    } else {
      this.form.reset({
        title: '',
        description: '',
        due_at: '',
        priority: 'med',
        assigned_to_id: this.callerUuid ?? '',
      });
    }
    this.error.set(null);
  }

  protected onSubmit(): void {
    if (this.form.invalid || this.saving()) return;
    const raw = this.form.getRawValue();
    const due_at = raw.due_at
      ? new Date(raw.due_at).toISOString()
      : null;
    const assignee = raw.assigned_to_id || this.callerUuid;
    if (!assignee) {
      this.error.set('Could not determine an assignee for this task.');
      return;
    }

    this.saving.set(true);
    this.error.set(null);

    if (this.task) {
      const update: TaskUpdate = {
        title: raw.title.trim(),
        description: raw.description.trim() || null,
        due_at,
        priority: raw.priority,
        assigned_to_id: assignee,
      };
      this.api
        .update(this.task.id, update)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (t) => {
            this.saving.set(false);
            this.saved.emit(t);
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.error.set(extractApiError(err) ?? 'Could not save the task.');
          },
        });
    } else {
      const create: TaskCreate = {
        title: raw.title.trim(),
        description: raw.description.trim() || null,
        due_at,
        priority: raw.priority,
        assigned_to_id: assignee,
      };
      this.api
        .create(create)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (t) => {
            this.saving.set(false);
            this.saved.emit(t);
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.error.set(extractApiError(err) ?? 'Could not create the task.');
          },
        });
    }
  }

  protected onCancel(): void {
    this.cancelled.emit();
  }
}
