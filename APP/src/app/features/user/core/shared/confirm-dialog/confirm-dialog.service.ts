import { Injectable, signal } from '@angular/core';

/**
 * Configurable options for a confirm-dialog `ask()` call. Mirrors the
 * `<app-confirm-dialog>` inputs one-to-one so a caller familiar with
 * the component API doesn't have to learn a new shape.
 */
export interface ConfirmDialogOptions {
  title: string;
  body?: string | null;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Paints the confirm button red for destructive actions. */
  danger?: boolean;
}

interface PendingConfirm extends ConfirmDialogOptions {
  resolve: (value: boolean) => void;
}

/**
 * App-wide confirm dialog. Replaces `window.confirm(...)` for any
 * destructive or otherwise consequential action so the messaging
 * (title + body + labels) and button styling can match the rest of
 * the UI.
 *
 * The service holds the pending dialog state; a single
 * `<app-confirm-dialog-host />` mounted in the app shell renders the
 * dialog when state is present.
 *
 * Usage:
 * ```ts
 * const ok = await this.confirmDialog.ask({
 *   title: 'Delete this node?',
 *   body: 'This also removes every edge attached to the node.',
 *   confirmLabel: 'Delete',
 *   danger: true,
 * });
 * if (!ok) return;
 * ```
 */
@Injectable({ providedIn: 'root' })
export class ConfirmDialogService {
  private readonly pendingSig = signal<PendingConfirm | null>(null);

  /** Snapshot of the currently pending dialog (`null` when none). */
  readonly pending = this.pendingSig.asReadonly();

  /** Open a confirm dialog. Resolves to `true` when the operator
   *  clicks the confirm button, `false` on cancel / dismiss. If a
   *  dialog is already open the previous one auto-resolves to false
   *  so the caller never leaks a hung promise. */
  ask(options: ConfirmDialogOptions): Promise<boolean> {
    const prev = this.pendingSig();
    if (prev) prev.resolve(false);
    return new Promise<boolean>((resolve) => {
      this.pendingSig.set({ ...options, resolve });
    });
  }

  /** Host-only — invoked from the dialog's confirm button. */
  confirm(): void {
    const p = this.pendingSig();
    if (!p) return;
    this.pendingSig.set(null);
    p.resolve(true);
  }

  /** Host-only — invoked from the dialog's cancel button or backdrop. */
  cancel(): void {
    const p = this.pendingSig();
    if (!p) return;
    this.pendingSig.set(null);
    p.resolve(false);
  }
}
