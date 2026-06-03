import type { LucideIconName } from '../icons';

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
 *   - `icon`          — lucide icon name, typed as `LucideIconName` so
 *                       missing-registration mistakes fail at TS compile
 *                       instead of throwing mid-render and silently
 *                       breaking click handlers further down the template.
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
  icon: LucideIconName;
  danger?: boolean;
  permissionKey?: string;
}
