import { CanDeactivateFn } from '@angular/router';

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
 * Pair it with a `window:beforeunload` listener in the component to
 * cover tab close / reload, which the router never sees.
 */
export const unsavedChangesGuard: CanDeactivateFn<HasUnsavedChanges> = (component) =>
  !component?.hasUnsavedChanges() ||
  window.confirm('You have unsaved changes. Leave this page and lose them?');
