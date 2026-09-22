import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { ConfirmDialogComponent } from './confirm-dialog.component';
import { ConfirmDialogService } from './confirm-dialog.service';
import { PromptDialogComponent } from './prompt-dialog.component';

/**
 * Global mount point for `ConfirmDialogService` — one instance sits
 * in the app shell (`shell.component.html`) alongside `<app-toast-host />`.
 * Any component can then call `ConfirmDialogService.ask(...)` or
 * `.prompt(...)` from anywhere in the app without wiring per-component
 * dialog state.
 */
@Component({
  selector: 'app-confirm-dialog-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ConfirmDialogComponent, PromptDialogComponent],
  template: `
    @if (svc.pending(); as p) {
      <app-confirm-dialog
        [title]="p.title"
        [body]="p.body ?? null"
        [confirmLabel]="p.confirmLabel ?? 'Confirm'"
        [cancelLabel]="p.cancelLabel ?? 'Cancel'"
        [danger]="!!p.danger"
        [hideCancel]="!!p.hideCancel"
        (confirm)="svc.confirm()"
        (cancel)="svc.cancel()"
      />
    }
    @if (svc.pendingPrompt(); as p) {
      <app-prompt-dialog
        [title]="p.title"
        [body]="p.body ?? null"
        [placeholder]="p.placeholder ?? ''"
        [initialValue]="p.initialValue ?? ''"
        [confirmLabel]="p.confirmLabel ?? 'Confirm'"
        [cancelLabel]="p.cancelLabel ?? 'Cancel'"
        (confirm)="svc.submitPrompt($event)"
        (cancel)="svc.cancelPrompt()"
      />
    }
  `,
})
export class ConfirmDialogHostComponent {
  protected readonly svc = inject(ConfirmDialogService);
}
