/**
 * Trims a form-control value and returns `null` if the result is
 * nullish or empty after trimming. Used by every "Create / Edit"
 * form modal to convert the `''` that reactive forms hand back for
 * untouched optional fields into a clean `null` on the wire.
 *
 *   nullableTrim('  Sofa  ') → 'Sofa'
 *   nullableTrim('')         → null
 *   nullableTrim('   ')      → null
 *   nullableTrim(null)       → null
 *   nullableTrim(undefined)  → null
 *
 * Accepts `unknown` to defend against form values that arrive as the
 * wrong runtime type — most commonly numbers emerging from
 * `<input type="number">` controls whose `FormControl` was declared
 * with a string default. The value is coerced via `String()` before
 * trimming so the function never throws on these mistyped inputs.
 *
 *   nullableTrim(15000)      → '15000'   (number from type="number")
 *   nullableTrim(false)      → 'false'   (boolean coercion)
 */
export function nullableTrim(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  const trimmed = String(v).trim();
  return trimmed.length === 0 ? null : trimmed;
}
