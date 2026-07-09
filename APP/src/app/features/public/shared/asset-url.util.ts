import { environment } from '../../../../environments/environment';

/**
 * Absolute-URL helper for backend-served asset paths (`/files/…`).
 *
 * The backend stores image URLs as storage-relative paths ("/files/{key}").
 * In dev the frontend (`localhost:4207`) and API (`localhost:30007`) run
 * on different origins — a bare `/files/…` in an <img> tag would resolve
 * against the frontend origin and 404. This helper prepends the API
 * host derived from `environment.apiBaseUrl` (which is `http://…/api/vN`)
 * so `<img src="…">` always hits the backend, dev or prod.
 *
 * Absolute URLs (already http/https) pass through unchanged. Empty /
 * null paths return an empty string so `<img src="">` degrades quietly.
 */
export function assetUrl(path: string | null | undefined): string {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  const apiHost = environment.apiBaseUrl.replace(/\/api\/v\d+\/?$/, '');
  return apiHost + (path.startsWith('/') ? path : '/' + path);
}
