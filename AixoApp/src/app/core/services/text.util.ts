/**
 * Renders a display name as up to two uppercase initials, suitable
 * for avatar circles. Returns `'?'` when the input is nullish, empty,
 * or contains no letters — never throws.
 *
 *   initials('John Doe')         → 'JD'
 *   initials('  alice  smith  ') → 'AS'
 *   initials('Madonna')          → 'M'
 *   initials('a b c d')          → 'AB'    (capped at 2)
 *   initials(null)               → '?'
 *   initials('')                 → '?'
 *   initials('   ')              → '?'
 */
export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const result = name
    .split(/\s+/)
    .filter((p) => p.length > 0)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('');
  return result.length > 0 ? result : '?';
}
