import { HttpErrorResponse } from '@angular/common/http';

/**
 * Extracts a human-readable message from an `HttpErrorResponse`.
 *
 * Looks for the message on `err.error` in this order:
 *   1. the body itself if it's a string (e.g. plain text 500)
 *   2. `.message` if it's a string (FastAPI's `{ message }` envelope)
 *   3. `.detail` if it's a string (FastAPI's default `{ detail }` envelope)
 *   4. `.detail` if it's a FastAPI request-validation list
 *      (`[{loc, msg}, ...]`) — flattened to "field: message" lines
 *   5. `.detail` if it's an object carrying `.message` or `.reason`
 *      (FastAPI HTTPException with a structured detail dict — e.g.
 *      `{ detail: { code: "invalid_graph", reason: "..." } }`)
 *
 * Returns `null` if no usable string is present so callers can fall
 * back to their own copy ("Could not save lead." etc.).
 */
export function extractApiError(err: HttpErrorResponse): string | null {
  const body = err?.error;
  if (typeof body === 'string') return body;
  if (body && typeof body === 'object') {
    const candidate =
      (body as { message?: string; detail?: unknown }).message ??
      (body as { detail?: unknown }).detail;
    if (typeof candidate === 'string') return candidate;
    if (Array.isArray(candidate)) {
      const lines = candidate
        .map((item: { loc?: unknown[]; msg?: string }) => {
          if (typeof item?.msg !== 'string') return null;
          const loc = Array.isArray(item.loc)
            ? item.loc.filter((p) => p !== 'body' && p !== 'query' && p !== 'path').join('.')
            : '';
          return loc ? `${loc}: ${item.msg}` : item.msg;
        })
        .filter((l): l is string => !!l);
      if (lines.length > 0) return lines.join('; ');
    }
    if (candidate && typeof candidate === 'object') {
      const nested = candidate as { message?: unknown; reason?: unknown };
      if (typeof nested.message === 'string') return nested.message;
      if (typeof nested.reason === 'string') return nested.reason;
    }
  }
  return null;
}
