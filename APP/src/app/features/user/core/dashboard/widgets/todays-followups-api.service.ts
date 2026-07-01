import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../shared/services/query-builder';

/** Mirrors `FollowupBucket` on the backend (`core/dashboard/schemas.py`). */
export type FollowupBucket = 'today' | 'pending' | 'completed_today' | 'overdue' | 'missed';

/** Mirrors `TaskFollowupType`. Kept aligned with the backend enum. */
export type FollowupType = 'call' | 'whatsapp' | 'email' | 'document' | 'meeting' | 'other';

/** Mirrors the four `TaskStatus` values relevant to this widget. */
export type FollowupStatus = 'open' | 'done' | 'cancelled' | 'missed';

/** Mirrors `TaskPriority`. */
export type FollowupPriority = 'low' | 'med' | 'high';

export interface FollowupCounts {
  today_total: number;
  pending_today: number;
  completed_today: number;
  overdue: number;
  missed_last_7d: number;
}

export interface FollowupAssignedTo {
  id: string;
  name: string;
}

export interface FollowupLinkedEntity {
  type: string;
  id: string;
  label: string;
}

export interface FollowupItem {
  id: string;
  title: string;
  due_at: string | null;
  priority: FollowupPriority;
  status: FollowupStatus;
  followup_type: FollowupType | null;
  notes_preview: string | null;
  assigned_to: FollowupAssignedTo;
  linked_entity: FollowupLinkedEntity | null;
}

export interface FollowupsResponse {
  scope: 'org' | 'personal';
  bucket: FollowupBucket;
  counts: FollowupCounts;
  page: number;
  page_size: number;
  total: number;
  items: FollowupItem[];
}

export interface FollowupsQuery {
  bucket?: FollowupBucket;
  assigned_to?: string;
  followup_type?: FollowupType;
  priority?: FollowupPriority;
  q?: string;
  page?: number;
  page_size?: number;
}

/**
 * HTTP wrapper for the Today's Follow-ups widget:
 *
 *  - `GET /api/v1/dashboard/followups` — bucketed list + counts.
 *  - `PATCH /api/v1/tasks/{id}` — reused for the inline Complete
 *    action (`{ status: 'done' }`) and the inline Reschedule
 *    (`{ due_at: '<iso>' }`) — the Tasks module already exposes
 *    both under this one endpoint.
 *
 * Kept intentionally thin — no state, no caching — because the
 * widget's own signals own the freshness contract. Poll cadence and
 * optimistic-update logic live in the component.
 */
@Injectable({ providedIn: 'root' })
export class TodaysFollowupsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(query: FollowupsQuery = {}): Observable<FollowupsResponse> {
    const params = buildHttpParams({
      bucket: query.bucket,
      assigned_to: query.assigned_to,
      followup_type: query.followup_type,
      priority: query.priority,
      q: query.q,
      page: query.page,
      page_size: query.page_size,
    });
    return this.http.get<FollowupsResponse>(`${this.base}/dashboard/followups`, {
      params,
    });
  }

  markDone(taskId: string): Observable<unknown> {
    return this.http.patch(`${this.base}/tasks/${taskId}`, { status: 'done' });
  }

  reschedule(taskId: string, isoDueAt: string): Observable<unknown> {
    return this.http.patch(`${this.base}/tasks/${taskId}`, { due_at: isoDueAt });
  }
}
