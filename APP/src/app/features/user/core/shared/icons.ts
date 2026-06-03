/**
 * Single source of truth for every lucide icon registered with
 * `LucideAngularModule.pick({...})` in `app/src/app/app.config.ts`.
 *
 * Each entry is the **kebab-case** name templates use:
 *
 *     <lucide-icon [name]="'user-cog'" />
 *     <lucide-icon name="trash-2" />
 *
 * The PascalCase symbol imports + `pick()` block in `app.config.ts`
 * must include every icon listed here. Adding a new icon is a two-
 * step change: import the PascalCase symbol in `app.config.ts` and
 * register it in the `pick()` object, then add its kebab-case name
 * to this array.
 *
 * `LucideIconName` is the derived string-literal union — use it as
 * the type for any prop that accepts an icon name (`BulkAction.icon`,
 * `<app-icon-button [icon]>`, dashboard quick-action configs, etc.).
 * Passing an unregistered string then fails at TS compile time
 * instead of throwing mid-render and silently breaking every click
 * handler downstream (per the project memory note on lucide icons).
 */
export const LUCIDE_ICONS = [
  'alert-triangle',
  'arrow-right',
  'arrow-right-circle',
  'banknote',
  'bell',
  'bookmark',
  'bookmark-check',
  'calendar',
  'calendar-clock',
  'camera',
  'check',
  'check-circle-2',
  'check-square',
  'chevron-down',
  'chevron-left',
  'chevron-right',
  'chevron-up',
  'circle-dashed',
  'circle-dot',
  'cog',
  'columns-3',
  'copy',
  'credit-card',
  'download',
  'file-spreadsheet',
  'footprints',
  'grip-vertical',
  'history',
  'image',
  'inbox',
  'layout-dashboard',
  'list',
  'loader-2',
  'log-out',
  'mail',
  'map-pin',
  'menu',
  'message-circle',
  'minus',
  'more-vertical',
  'package',
  'pencil',
  'phone',
  'plus',
  'printer',
  'receipt',
  'refresh-cw',
  'ruler',
  'search',
  'sliders-horizontal',
  'smartphone',
  'sticky-note',
  'tag',
  'target',
  'trash-2',
  'upload',
  'upload-cloud',
  'user',
  'user-check',
  'user-cog',
  'user-plus',
  'user-x',
  'users',
  'wallet',
  'warehouse',
  'x',
  'x-circle',
] as const;

export type LucideIconName = (typeof LUCIDE_ICONS)[number];
