/**
 * One row in the floating bulk-action toolbar.
 *
 * Shared across every list page (contacts, leads, tasks, walk-ins,
 * appointments, …) — each page provides its own array and
 * `ListPageState` carries it through to the `<app-bulk-action-bar>`.
 *
 * Fields:
 *   - `key`           — passed back via the bar's `(action)` output so the
 *                       parent dispatches to a handler (open reassign
 *                       modal, open confirm dialog, etc.).
 *   - `label`         — button text.
 *   - `icon`          — lucide icon name (must be registered in
 *                       `app.config.ts::LucideAngularModule.pick(...)` —
 *                       missing icons render as empty boxes and silently
 *                       break click handlers further down the template).
 *   - `danger?`       — when `true`, button renders red. Used for
 *                       destructive actions like Delete.
 *   - `permissionKey?` — checked against the signed-in user's
 *                       permissions; actions the user can't take are
 *                       HIDDEN (not disabled) to avoid the "what was that
 *                       button?" confusion. `undefined` means everyone
 *                       with list access can take the action.
 */
export interface BulkAction {
  key: string;
  label: string;
  icon: string;
  danger?: boolean;
  permissionKey?: string;
}
