import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { ColumnDef } from '../shared/column-prefs.service';
import { FilterDsl } from '../shared/filter-dsl.types';

/** Entities the saved-views API will accept. Widen as future list pages
 * (contacts, walk-ins, tasks) wire up their menus. Keep aligned with the
 * backend's `SavedViewCreate.entity` Literal. */
export type SavedViewEntity = 'leads';

export type SavedViewScope = 'mine' | 'team' | 'all';
export type SavedViewMode = 'list' | 'pipeline';
export type SavedViewSortOrder = 'asc' | 'desc';

/**
 * Configuration bundle a saved view restores. Every field is optional —
 * a missing key means "use the page default." Mirrors the backend's
 * `SavedViewConfig` (`api/src/app/core/saved_views/schemas.py`).
 */
export interface SavedViewConfig {
  filter?: FilterDsl;
  sort?: string;
  order?: SavedViewSortOrder;
  scope?: SavedViewScope;
  columns?: ColumnDef[];
  view?: SavedViewMode;
}

export interface SavedView {
  id: string;
  org_id: string;
  owner_user_id: string;
  entity: SavedViewEntity;
  name: string;
  config: SavedViewConfig;
  shared: boolean;
  created_at: string;
  updated_at: string;
}

export interface SavedViewCreate {
  entity: SavedViewEntity;
  name: string;
  config: SavedViewConfig;
  shared?: boolean;
}

export interface SavedViewUpdate {
  name?: string;
  config?: SavedViewConfig;
  shared?: boolean;
}

/**
 * REST client for `/api/v1/saved-views`. Owned + shared visibility is
 * already enforced server-side; the FE doesn't filter — it just renders.
 *
 * Retry / 401 handling rides on the global interceptors per the project
 * convention.
 */
@Injectable({ providedIn: 'root' })
export class SavedViewsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/saved-views`;

  list(entity: SavedViewEntity): Observable<SavedView[]> {
    const params = new HttpParams().set('entity', entity);
    return this.http.get<SavedView[]>(this.base, { params });
  }

  create(payload: SavedViewCreate): Observable<SavedView> {
    return this.http.post<SavedView>(this.base, payload);
  }

  update(id: string, payload: SavedViewUpdate): Observable<SavedView> {
    return this.http.patch<SavedView>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
