/**
 * Trims a form-control string and returns `null` if the result is
 * nullish or empty after trimming. Used by every "Create / Edit"
 * form modal to convert the `''` that reactive forms hand back for
 * untouched optional fields into a clean `null` on the wire.
 *
 *   nullableTrim('  Sofa  ') → 'Sofa'
 *   nullableTrim('')         → null
 *   nullableTrim('   ')      → null
 *   nullableTrim(null)       → null
 *   nullableTrim(undefined)  → null
 */
export function nullableTrim(v: string | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  const trimmed = v.trim();
  return trimmed.length === 0 ? null : trimmed;
}
