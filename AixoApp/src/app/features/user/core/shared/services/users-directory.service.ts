import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/** Server-side cap on `GET /users` is 200. Owner-picker dropdowns
 *  should surface every active seat in the org; a 50-row default cap
 *  silently truncated the tail for orgs with > 50 users, so the
 *  operator couldn't reassign to people alphabetically past the 50th. */
const USER_DIRECTORY_LIMIT = 200;

/**
 * Minimal user shape needed by owner dropdowns / assignee filters on
 * list pages (contacts, leads, walk-ins, appointments, tasks). The
 * backend `GET /users` returns the full `UserOut` shape — we only
 * surface the columns the UI binds to.
 */
export interface UserMini {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

/**
 * Caches the per-tenant user list for the session. `shareReplay`
 * with `bufferSize=1, refCount=false` means: the HTTP call fires
 * once and every later subscriber gets the same buffered list
 * without a re-fetch. Built for owner-picker dropdowns where the
 * roster is read-mostly within a sales rep's session.
 *
 * Consumers that need a fresh list after a known mutation (e.g.
 * the Staff settings page after invite / deactivate) call
 * `invalidate()` then re-`list()`.
 */
@Injectable({ providedIn: 'root' })
export class UsersDirectoryService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiBaseUrl}/users`;
  private cache$: Observable<UserMini[]> | null = null;

  list(): Observable<UserMini[]> {
    if (!this.cache$) {
      const params = new HttpParams().set('limit', String(USER_DIRECTORY_LIMIT));
      this.cache$ = this.http
        .get<UserMini[]>(this.url, { params })
        .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    }
    return this.cache$;
  }

  invalidate(): void {
    this.cache$ = null;
  }
}
