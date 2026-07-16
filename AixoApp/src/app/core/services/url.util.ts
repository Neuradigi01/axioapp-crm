import { environment } from '../../../environments/environment';

/**
 * Returns the origin of the configured API base URL (scheme + host +
 * port), with no trailing slash. Used when callers need to open a file
 * served by the backend in a new tab — e.g. an invoice PDF or a field
 * visit photo — and the API path comes back as a server-relative URL
 * like `/storage/...` that must be re-anchored to the API host, not the
 * Angular dev origin.
 *
 *   apiBaseUrl='http://localhost:8000/api/v1' → 'http://localhost:8000'
 *
 * Returns `''` if `apiBaseUrl` can't be parsed, so callers can safely
 * concatenate without a runtime exception.
 */
export function deriveApiOrigin(): string {
  try {
    return new URL(environment.apiBaseUrl, window.location.origin).origin;
  } catch {
    return '';
  }
}
