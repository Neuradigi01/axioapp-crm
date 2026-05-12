import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

/**
 * Activity types mirror `ActivityType` from
 * `api/src/app/core/activities/models.py`. Keep these in sync — adding
 * a new value here without the backend enum picking it up will not
 * make the new value safe to send.
 */
export type ActivityType =
  | 'note'
  | 'call'
  | 'email'
  | 'whatsapp'
  | 'status_change'
  | 'task';

export interface Activity {
  id: string;
  org_id: string;
  entity_type: string;
  entity_id: string;
  type: ActivityType;
  payload: Record<string, unknown>;
  user_id: string | null;
  created_at: string;
}

export interface ActivityListResponse {
  items: Activity[];
  total: number;
  page: number;
  size: number;
}

@Injectable({ providedIn: 'root' })
export class ActivitiesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/activities`;

  list(
    entityType: string,
    entityId: string,
    page = 1,
    size = 50,
  ): Observable<ActivityListResponse> {
    const params = new HttpParams()
      .set('entity_type', entityType)
      .set('entity_id', entityId)
      .set('page', String(page))
      .set('size', String(size));
    return this.http.get<ActivityListResponse>(this.base, { params });
  }

  /**
   * Manual notes only — other activity types are server-emitted from
   * inside the backend (call ended, status changed, …) and rejected by
   * the API when posted from the browser.
   */
  createNote(
    entityType: string,
    entityId: string,
    text: string,
  ): Observable<Activity> {
    return this.http.post<Activity>(this.base, {
      entity_type: entityType,
      entity_id: entityId,
      type: 'note',
      payload: { text },
    });
  }
}
