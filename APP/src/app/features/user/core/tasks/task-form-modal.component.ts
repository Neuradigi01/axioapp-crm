import {
  ChangeDetectionStrategy,
  Component,
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
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Observable, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import { BaseFormModalComponent } from '../shared/components/base-form-modal.component';
import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import type { StandardFieldRendered } from '../standard-fields/types';
import { commonValidators, withRequiredIf } from '../shared/validators';

import {
  Task,
  TaskCreate,
  TaskFollowupType,
  TaskPriority,
  TaskUpdate,
  TasksApiService,
} from './tasks-api.service';

export interface TaskAssignee {
  id: string;
  full_name: string;
  email: string;
}

/** Followup-type picklist. Mirrors the backend `TaskFollowupType` enum
 *  1:1 — keep in sync. First entry is the "none / generic to-do"
 *  option submitted as null. */
const FOLLOWUP_OPTIONS: ReadonlyArray<{
  value: '' | TaskFollowupType;
  label: string;
}> = [
  { value: '', label: '— (generic to-do)' },
  { value: 'call', label: 'Call' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'document', label: 'Document' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'other', label: 'Other' },
];

/**
 * Create-or-edit task modal. Same form for both flows; `task` input
 * decides mode. Assignee dropdown comes from the parent (it knows
 * whether the caller has `users.read` to load the full list, or
 * should default to self only).
 *
 * Widened (tasks review) with:
 *   T3 — followup_type select
 *   T4 — dynamic custom-field renderer (via `TasksApiService.renderFields`)
 *   T5 — contact search-picker for `related_entity` linkage
 */
@Component({
  selector: 'app-task-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, DynamicFormComponent],
  templateUrl: './task-form-modal.component.html',
})
export class TaskFormModalComponent extends BaseFormModalComponent {
  protected readonly entityType = 'task';

  private readonly api = inject(TasksApiService);
  private readonly fb = inject(FormBuilder);
  private readonly contactsApi = inject(ContactsApiService);

  /** T4 — Task custom fields backed by the standard
   *  `GET /custom-fields/task/render` endpoint (added by the tasks
   *  review; DB column shipped in migration 0162). Was previously a
   *  stub returning `of([])`. */
  protected renderCustomFields$(): Observable<FieldDef[]> {
    return this.api.renderFields();
  }

  /** `title` + `priority` stay always-required (registry locks both).
   *  `description` / `due_at` / `assigned_to_id` accept the `required` override. */
  protected applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    this.form.controls.title.setValidators([
      commonValidators.required,
      commonValidators.maxLength(255),
    ]);
    this.form.controls.title.updateValueAndValidity({ emitEvent: false });
    this.form.controls.priority.setValidators([commonValidators.required]);
    this.form.controls.priority.updateValueAndValidity({ emitEvent: false });

    const setReq = (
      ctrl: 'description' | 'due_at' | 'assigned_to_id',
      row: StandardFieldRendered | undefined,
    ): void => {
      this.form.controls[ctrl].setValidators(withRequiredIf([], row));
      this.form.controls[ctrl].updateValueAndValidity({ emitEvent: false });
    };
    setReq('description', map['description']);
    setReq('due_at', map['due_at']);
    setReq('assigned_to_id', map['assigned_to_id']);
  }

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
  protected readonly followupOptions = FOLLOWUP_OPTIONS;

  protected readonly form = this.fb.nonNullable.group({
    title: ['', [commonValidators.required, commonValidators.maxLength(255)]],
    description: [''],
    due_at: [''],
    priority: ['med' as TaskPriority, commonValidators.required],
    assigned_to_id: [''],
    followup_type: ['' as '' | TaskFollowupType],
  });

  protected readonly hasAssigneeDropdown = computed(() => this.assignees.length > 0);
  protected readonly isEdit = computed(() => this.task !== null);

  // T5 — contact picker state. Optional on every task; when set, the
  // task gets `related_entity_type='contact' + related_entity_id`.
  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactSearch = signal('');
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearching = signal(false);
  private readonly contactSearch$ = new Subject<string>();

  constructor() {
    super();
    this.contactSearch$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => {
          const trimmed = q.trim();
          if (trimmed.length < 2) {
            this.contactSearching.set(false);
            return [{ items: [] as ContactListItem[] }];
          }
          this.contactSearching.set(true);
          return this.contactsApi.list({ q: trimmed, size: 10 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.contactResults.set(resp.items);
          this.contactSearching.set(false);
        },
        error: () => this.contactSearching.set(false),
      });
  }

  protected onContactSearchInput(event: Event): void {
    const v = (event.target as HTMLInputElement).value;
    this.contactSearch.set(v);
    this.contactSearch$.next(v);
  }

  protected pickContact(row: ContactListItem): void {
    this.selectedContact.set(row);
    this.contactResults.set([]);
    this.contactSearch.set('');
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.contactSearch.set('');
    this.contactResults.set([]);
  }

  protected onCustomValueChange(v: FormValue): void {
    this.customValue.set(v);
  }

  protected onCustomValidityChange(valid: boolean): void {
    this.customValid.set(valid);
  }

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
        followup_type: (this.task.followup_type ?? '') as '' | TaskFollowupType,
      });
      // Seed the custom form with the task's persisted values so the
      // dynamic renderer paints the current state on open.
      this.customValue.set((this.task.custom_data ?? {}) as FormValue);
      // Related-entity chip only supports contact linkage in the
      // picker; when the task is linked to a lead / other entity the
      // picker starts blank and the operator can re-link if desired.
      if (this.task.related_entity_type === 'contact' && this.task.related_entity_id) {
        // Lazy fetch of the linked contact so the chip renders full
        // name / phone / email without the operator re-searching.
        this.contactsApi
          .get(this.task.related_entity_id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: (c) =>
              this.selectedContact.set({
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
                email: c.email,
                source: c.source,
                tags: c.tags ?? [],
                assigned_to_id: c.assigned_to_id,
                last_activity_at: c.last_activity_at,
                created_at: c.created_at,
              } as ContactListItem),
            error: () => this.selectedContact.set(null),
          });
      } else {
        this.selectedContact.set(null);
      }
    } else {
      this.form.reset({
        title: '',
        description: '',
        due_at: '',
        priority: 'med',
        assigned_to_id: this.callerUuid ?? '',
        followup_type: '',
      });
      this.customValue.set({});
      this.selectedContact.set(null);
    }
    this.contactSearch.set('');
    this.contactResults.set([]);
    this.error.set(null);
  }

  protected onSubmit(): void {
    if (this.form.invalid || this.saving()) return;
    if (!this.customValid()) {
      this.error.set('Please fix the highlighted custom fields.');
      return;
    }
    const raw = this.form.getRawValue();
    const due_at = raw.due_at ? new Date(raw.due_at).toISOString() : null;
    const assignee = raw.assigned_to_id || this.callerUuid;
    if (!assignee) {
      this.error.set('Could not determine an assignee for this task.');
      return;
    }
    const contact = this.selectedContact();
    const followup = raw.followup_type || null;
    const customData = this.customValue() as Record<string, unknown>;

    this.saving.set(true);
    this.error.set(null);

    if (this.task) {
      const update: TaskUpdate = {
        title: raw.title.trim(),
        description: raw.description.trim() || null,
        due_at,
        priority: raw.priority,
        assigned_to_id: assignee,
        followup_type: followup,
        custom_data: customData,
        // On edit, only rewrite the linkage when the operator changed
        // something (either picked a new contact or cleared it). Leave
        // untouched otherwise so we don't accidentally strip a non-
        // contact link (e.g. a lead-linked task).
        ...(contact
          ? { related_entity_type: 'contact', related_entity_id: contact.id }
          : this.task.related_entity_type === 'contact'
            ? { related_entity_type: null, related_entity_id: null }
            : {}),
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
        followup_type: followup,
        custom_data: customData,
        ...(contact ? { related_entity_type: 'contact', related_entity_id: contact.id } : {}),
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
