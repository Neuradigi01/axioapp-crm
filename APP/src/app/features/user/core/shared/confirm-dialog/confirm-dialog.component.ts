import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

/**
 * Standard styled confirmation dialog. Replaces `window.confirm` for
 * any destructive or otherwise consequential action so the messaging
 * (title + body) and button styling can match the rest of the UI.
 *
 * Usage:
 *
 *   <app-confirm-dialog
 *     [title]="'Delete 3 contacts?'"
 *     [body]="'This cannot be undone.'"
 *     [confirmLabel]="'Delete'"
 *     [danger]="true"
 *     (confirm)="onConfirm()"
 *     (cancel)="onCancel()"
 *   />
 *
 * Reused across the contacts, leads, walk-ins, appointments, and
 * tasks pages.
 */
@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './confirm-dialog.component.html',
})
export class ConfirmDialogComponent {
  @Input() title = 'Are you sure?';
  @Input() body: string | null = null;
  @Input() confirmLabel = 'Confirm';
  @Input() cancelLabel = 'Cancel';
  @Input() danger = false;
  @Input() submitting = false;
  @Input() error: string | null = null;
  /** Hide the Cancel button — turns the dialog into an OK-only info
   *  prompt for cases where the operator has no meaningful choice
   *  (e.g. "None of the selected campaigns are deletable"). */
  @Input() hideCancel = false;

  @Output() readonly confirm = new EventEmitter<void>();
  @Output() readonly cancel = new EventEmitter<void>();
}
