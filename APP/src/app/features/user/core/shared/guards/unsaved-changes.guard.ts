import { inject } from '@angular/core';
import { CanDeactivateFn } from '@angular/router';

import { ConfirmDialogService } from '../confirm-dialog/confirm-dialog.service';

/** Implemented by pages with an editor that can hold unsaved input. */
export interface HasUnsavedChanges {
  hasUnsavedChanges(): boolean;
}

/**
 * Route guard: asks before leaving a page that has unsaved changes.
 * Add to any route whose component implements `HasUnsavedChanges`:
 *
 *   { path: ':id', component: MyEditor, canDeactivate: [unsavedChangesGuard] }
 *
 * Uses the app's themed confirm dialog (rendered by the shell's
 * `<app-confirm-dialog-host />`) instead of the native browser alert.
 *
 * Pair it with a `window:beforeunload` listener in the component to
 * cover tab close / reload, which the router never sees.
 */
export const unsavedChangesGuard: CanDeactivateFn<HasUnsavedChanges> = (component) => {
  if (!component?.hasUnsavedChanges()) return true;
  return inject(ConfirmDialogService).ask({
    title: 'Discard unsaved changes?',
    body: 'You have unsaved changes. Leave this page and lose them?',
    confirmLabel: 'Leave page',
    cancelLabel: 'Stay',
    danger: true,
  });
};
