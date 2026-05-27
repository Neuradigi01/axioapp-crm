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
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { UsersDirectoryService } from '../services/users-directory.service';

/**
 * Payload emitted on confirm. `userId === null` means "Unassigned"
 * (the parent passes through to the backend, which clears
 * `assigned_to_id`). `note` is an optional free-text annotation that
 * the backend writes onto the audit activity payload.
 */
export interface ReassignConfirm {
  userId: string | null;
  note: string | null;
}

/**
 * Owner-picker modal shared across contacts, leads, walk-ins,
 * appointments, and tasks. Purely presentational — emits
 * `(confirm)` / `(cancel)`; the parent component owns the API call.
 *
 *   <app-reassign-modal
 *     [entityLabel]="'contact'"
 *     [count]="3"
 *     [currentOwnerId]="contact.assigned_to_id"
 *     [submitting]="reassigning()"
 *     (confirm)="onReassign($event)"
 *     (cancel)="closeReassign()"
 *   />
 *
 * For a single-row reassign the parent passes `count=1` and the
 * current owner id (which we use to skip a no-op submission and to
 * preselect the dropdown). For a bulk reassign the parent passes
 * `count=N` and omits the current owner (different rows likely have
 * different owners; the dropdown defaults to Unassigned).
 */
@Component({
  selector: 'app-reassign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './reassign-modal.component.html',
})
export class ReassignModalComponent {
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly _entityLabel = signal('record');
  protected readonly _count = signal(1);
  protected readonly _currentOwnerId = signal<string | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set entityLabel(value: string) {
    this._entityLabel.set(value);
  }

  @Input() set count(n: number) {
    this._count.set(n);
  }

  /** Current owner of the row being reassigned (single-mode only). */
  @Input() set currentOwnerId(value: string | null | undefined) {
    const v = value ?? null;
    this._currentOwnerId.set(v);
    this.userControl.setValue(v ?? '', { emitEvent: false });
  }

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Input() set error(value: string | null) {
    this._error.set(value);
  }

  @Output() readonly confirm = new EventEmitter<ReassignConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  /** Selected user id (empty string for "Unassigned"). */
  protected readonly userControl = new FormControl<string>('', {
    nonNullable: true,
  });
  /** Optional audit note. */
  protected readonly noteControl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected readonly users = toSignal(
    this.usersDir.list().pipe(takeUntilDestroyed(this.destroyRef)),
    { initialValue: [] },
  );

  /** Heading line: "Reassign 1 contact" or "Reassign 12 contacts". */
  protected readonly heading = computed(() => {
    const n = this._count();
    const label = this._entityLabel();
    const plural = n === 1 ? label : `${label}s`;
    return `Reassign ${n} ${plural}`;
  });

  /** Disable confirm when nothing's selected for a no-owner-change attempt. */
  protected readonly canConfirm = computed(() => {
    if (this._submitting()) return false;
    const picked = this.userControl.value || null;
    const current = this._currentOwnerId();
    // Bulk mode (no currentOwnerId reference) → always allow.
    if (current === null && picked === null) {
      // Bulk + "Unassigned" picked — still valid.
      return true;
    }
    return picked !== current;
  });

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    const userId = this.userControl.value || null;
    const noteRaw = this.noteControl.value.trim();
    this.confirm.emit({
      userId,
      note: noteRaw.length > 0 ? noteRaw : null,
    });
  }
}
