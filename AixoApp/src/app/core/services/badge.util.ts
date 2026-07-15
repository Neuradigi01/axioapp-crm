/**
 * Maps a field-visit `purpose` string to the Tailwind classes that render
 * its rounded ring-badge. Unknown / missing purposes fall back to a
 * neutral zinc badge so the UI never shows a blank pill.
 *
 *   purposeBadgeClass('measurement')  → sky badge
 *   purposeBadgeClass('installation') → amber badge
 *   purposeBadgeClass('inspection')   → violet badge
 *   purposeBadgeClass('delivery')     → zinc badge   (default)
 *   purposeBadgeClass('')             → zinc badge   (default)
 */
export function purposeBadgeClass(purpose: string): string {
  switch (purpose) {
    case 'measurement':
      return 'bg-sky-100 text-sky-700 ring-sky-200';
    case 'installation':
      return 'bg-amber-100 text-amber-700 ring-amber-200';
    case 'inspection':
      return 'bg-violet-100 text-violet-700 ring-violet-200';
    default:
      return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
  }
}
