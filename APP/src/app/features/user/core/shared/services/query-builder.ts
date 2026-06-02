import { HttpParams } from '@angular/common/http';

/**
 * Build an `HttpParams` instance from a flat key/value record.
 *
 * Every list-page API service used to ship a hand-rolled chain of
 * `if (query.x) params = params.set('x', String(query.x))` lines. This
 * utility consolidates them.
 *
 * Behaviour:
 * - Entries whose value is `undefined`, `null`, or the empty string
 *   `''` are skipped. Defined `0` and `false` ARE preserved — a
 *   meaningful filter like `with_total=false` reaches the wire as
 *   `with_total=false`.
 * - Arrays are serialized as repeated keys: `{ tags: ['a', 'b'] }`
 *   becomes `?tags=a&tags=b`. Empty arrays and array elements that
 *   are themselves skip-worthy (undefined/null/'') are dropped.
 * - All other values are stringified via `String(value)`; `HttpParams`
 *   itself accepts `string | number | boolean`.
 *
 * Callers that need composite behaviour (e.g. `custom.X` prefixes for
 * the dynamic-field filter pattern, `JSON.stringify(filter)` for the
 * leads filter DSL) should flatten/serialize their input record
 * before passing it in.
 *
 * @example
 *   const params = buildHttpParams({
 *     q: query.q,
 *     page: query.page,
 *     size: query.size,
 *     tags: query.tags,            // string[]
 *     with_total: query.with_total // boolean — false is preserved
 *   });
 */
export function buildHttpParams(
  query: Record<string, unknown>,
): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === '') continue;
        params = params.append(key, String(item));
      }
      continue;
    }
    params = params.set(key, String(value));
  }
  return params;
}

/**
 * Helper for the dynamic-custom-fields filter convention: turn a flat
 * `{ key: value }` record into a `{ 'custom.key': value }` record so it
 * can be spread into a `buildHttpParams({ ... })` call. Returns an
 * empty object when the input is undefined.
 *
 * @example
 *   const params = buildHttpParams({
 *     q: query.q,
 *     ...prefixCustomFilters(query.customFilters),
 *   });
 */
export function prefixCustomFilters(
  customFilters: Record<string, unknown> | undefined,
): Record<string, unknown> {
  if (!customFilters) return {};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(customFilters)) {
    out[`custom.${key}`] = value;
  }
  return out;
}
