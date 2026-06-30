import { HttpErrorResponse } from '@angular/common/http';

/**
 * Extracts a human-readable message from an `HttpErrorResponse`.
 *
 * Looks for the message on `err.error` in this order:
 *   1. the body itself if it's a string (e.g. plain text 500)
 *   2. `.message` if it's a string (FastAPI's `{ message }` envelope)
 *   3. `.detail` if it's a string (FastAPI's default `{ detail }` envelope)
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
  }
  return null;
}
