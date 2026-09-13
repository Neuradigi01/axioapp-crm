import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, of, shareReplay, tap } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface BotVariable {
  path: string;
  label: string;
  description?: string | null;
  sample?: string | null;
}

export interface BotVariableGroup {
  key: string;
  label: string;
  variables: BotVariable[];
}

export interface BotVariablesResponse {
  groups: BotVariableGroup[];
}

/**
 * Fetches `/api/v1/chatbots/variables` — the picker source for the
 * builder's variable-picker component + the canvas Variables panel.
 *
 * The response is org-wide + static per-session, so we cache the first
 * fetch in-memory via `shareReplay(1)` and hand every subsequent caller
 * the same observable. Cache-bust with `refresh()` when a custom field
 * is added elsewhere in the app.
 */
@Injectable({ providedIn: 'root' })
export class VariablePickerApiService {
  private readonly http = inject(HttpClient);
  private cached$: Observable<BotVariablesResponse> | null = null;

  list(): Observable<BotVariablesResponse> {
    if (!this.cached$) {
      this.cached$ = this.http
        .get<BotVariablesResponse>(`${environment.apiBaseUrl}/chatbots/variables`)
        .pipe(
          shareReplay({ bufferSize: 1, refCount: false }),
          // Defensively guard against a bad response so the picker's
          // dropdown always has something to render.
          tap({
            error: () => {
              // On error, drop the cache so a future call re-fetches.
              this.cached$ = null;
            },
          }),
        );
    }
    return this.cached$;
  }

  /** Bust the in-memory cache. Call after adding a custom field so the
   *  picker picks it up on next `list()`. */
  refresh(): Observable<BotVariablesResponse> {
    this.cached$ = null;
    return this.list();
  }

  /** Empty response — used as a placeholder before the HTTP request
   *  resolves and as a safe fallback if the API is unreachable. */
  empty(): Observable<BotVariablesResponse> {
    return of({ groups: [] });
  }
}
