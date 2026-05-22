import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import type {
  StandardFieldEntitiesResponse,
  StandardFieldOverrideIn,
  StandardFieldOverrideOut,
  StandardFieldRendered,
  StandardFieldRenderedListResponse,
} from './types';

/**
 * Wraps `/api/v1/standard-fields/*` for the Settings tab (and the form
 * modals in Steps 5/6).
 *
 *   entities()              → GET  /standard-fields/entities
 *   render(entity)          → GET  /standard-fields/{entity}/render   (open to any user)
 *   upsert(entity, key, p)  → PUT  /standard-fields/{entity}/{key}    (manage permission)
 *   reset(entity, key)      → DEL  /standard-fields/{entity}/{key}    (manage permission)
 */
@Injectable({ providedIn: 'root' })
export class StandardFieldsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/standard-fields`;

  entities(): Observable<StandardFieldEntitiesResponse> {
    return this.http.get<StandardFieldEntitiesResponse>(`${this.base}/entities`);
  }

  render(entity: string): Observable<StandardFieldRenderedListResponse> {
    return this.http.get<StandardFieldRenderedListResponse>(
      `${this.base}/${entity}/render`,
    );
  }

  upsert(
    entity: string,
    fieldKey: string,
    payload: StandardFieldOverrideIn,
  ): Observable<StandardFieldOverrideOut> {
    return this.http.put<StandardFieldOverrideOut>(
      `${this.base}/${entity}/${fieldKey}`,
      payload,
    );
  }

  reset(entity: string, fieldKey: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${entity}/${fieldKey}`);
  }
}

/** Re-export so consumers can import the merged-field shape from the service module. */
export type { StandardFieldRendered };
