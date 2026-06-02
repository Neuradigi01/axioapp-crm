import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

/**
 * Mirrors `TaskStatus` / `TaskPriority` from the backend. Keep these
 * unions in sync with `api/src/app/core/tasks/models.py` — new values
 * here without the backend enum will be rejected at HTTP boundary.
 */
export type TaskStatus = 'open' | 'done' | 'cancelled';
export type TaskPriority = 'low' | 'med' | 'high';
export type TaskDueFilter = 'today' | 'overdue' | 'upcoming';
export type TaskSortBy =
  | 'due_at'
  | 'priority'
  | 'title'
  | 'created_at'
  | 'last_activity_at';
export type TaskSortDir = 'asc' | 'desc';

export interface TaskListFilters {
  status?: TaskStatus;
  priority?: TaskPriority;
  q?: string;
  due_filter?: TaskDueFilter;
  sort_by?: TaskSortBy;
  sort_dir?: TaskSortDir;
  assigned_to_id?: string;
  page?: number;
  size?: number;
}

export interface Task {
  id: string;
  org_id: string;
  title: string;
  description: string | null;
  due_at: string | null;
  assigned_to_id: string;
  related_entity_type: string | null;
  related_entity_id: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  last_activity_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  items: Task[];
  total: number;
  page: number;
  size: number;
}

export interface TaskCreate {
  title: string;
  description?: string | null;
  due_at?: string | null;
  assigned_to_id?: string | null;
  related_entity_type?: string | null;
  related_entity_id?: string | null;
  priority?: TaskPriority;
}

export type TaskUpdate = Partial<{
  title: string;
  description: string | null;
  due_at: string | null;
  assigned_to_id: string | null;
  status: TaskStatus;
  priority: TaskPriority;
}>;

function toParams(filters: TaskListFilters) {
  return buildHttpParams({
    status: filters.status,
    priority: filters.priority,
    q: filters.q,
    due_filter: filters.due_filter,
    sort_by: filters.sort_by,
    sort_dir: filters.sort_dir,
    assigned_to_id: filters.assigned_to_id,
    page: filters.page,
    size: filters.size,
  });
}

@Injectable({ providedIn: 'root' })
export class TasksApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/tasks`;

  /** Tasks attached to one entity (panel inside contact/lead detail). */
  listForEntity(
    entityType: string,
    entityId: string,
    status?: TaskStatus,
  ): Observable<TaskListResponse> {
    const params = buildHttpParams({
      related_entity_type: entityType,
      related_entity_id: entityId,
      status,
    });
    return this.http.get<TaskListResponse>(this.base, { params });
  }

  /** Caller's own tasks. Used by the header popover (no filters) and the
   *  Tasks page (all filter params). */
  listMine(filters: TaskListFilters = {}): Observable<TaskListResponse> {
    return this.http.get<TaskListResponse>(`${this.base}/me`, {
      params: toParams(filters),
    });
  }

  /** Every task in the org. Requires `users.read` server-side; callers
   *  without it get 403. Used by the Tasks page's "All" chip. */
  listAll(filters: TaskListFilters = {}): Observable<TaskListResponse> {
    return this.http.get<TaskListResponse>(`${this.base}/all`, {
      params: toParams(filters),
    });
  }

  create(payload: TaskCreate): Observable<Task> {
    return this.http.post<Task>(this.base, payload);
  }

  update(id: string, payload: TaskUpdate): Observable<Task> {
    return this.http.patch<Task>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Bulk reassign N tasks to `userId`. Tasks require an owner — the
   * server rejects null. Audit `reassign` activities are written per
   * row. */
  bulkReassign(
    ids: string[],
    body: { userId: string; note?: string | null },
  ): Observable<{ reassigned: number }> {
    return this.http.post<{ reassigned: number }>(
      `${this.base}/bulk-reassign`,
      {
        ids,
        assigned_to_id: body.userId,
        note: body.note ?? null,
      },
    );
  }

  /** Bulk mark-done. Already-done rows are skipped (counted). Returns
   * `{done, skipped}` so the FE can surface partial success. */
  bulkMarkDone(
    ids: string[],
  ): Observable<{ done: number; skipped: number }> {
    return this.http.post<{ done: number; skipped: number }>(
      `${this.base}/bulk-mark-done`,
      { ids },
    );
  }

  bulkDelete(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${this.base}/bulk-delete`, {
      ids,
    });
  }
}
