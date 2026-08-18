/**
 * Generic column-filter contract.
 *
 * `app-column-filter` is a reusable table-header dropdown any list
 * page can drop onto a `<th>`. This file holds the type surface every
 * page shares so a future Leads / Deals / Properties / Tasks table
 * can declare filter columns without importing anything Contacts-specific.
 *
 * The mechanism is deliberately transport-agnostic: the popover emits
 * the selected value(s) as a plain `string[]`. Each page decides how
 * to translate that into its own API query — no shared HTTP call, no
 * shared entity assumption.
 */

/**
 * Filter widget rendered inside the popover.
 *
 * - `multi-select` — searchable checkbox list. Emits every checked
 *   value as a `string[]`. Current UI ships this shape only; the
 *   other names are typed placeholders so pages can already declare
 *   the intended widget in their column config today and the popover
 *   grows to serve them without a config-shape churn tomorrow.
 * - `select` — single-value radio list. Reserved.
 * - `text` — plain text input. Reserved.
 */
export type ColumnFilterType = 'multi-select' | 'select' | 'text';

/** One row inside the popover's option list. */
export interface ColumnFilterOption {
  readonly value: string;
  readonly label: string;
}
