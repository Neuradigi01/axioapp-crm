import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

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

function toParams(filters: TaskListFilters): HttpParams {
  let params = new HttpParams();
  if (filters.status) params = params.set('status', filters.status);
  if (filters.priority) params = params.set('priority', filters.priority);
  if (filters.q) params = params.set('q', filters.q);
  if (filters.due_filter) params = params.set('due_filter', filters.due_filter);
  if (filters.sort_by) params = params.set('sort_by', filters.sort_by);
  if (filters.sort_dir) params = params.set('sort_dir', filters.sort_dir);
  if (filters.assigned_to_id)
    params = params.set('assigned_to_id', filters.assigned_to_id);
  if (filters.page) params = params.set('page', String(filters.page));
  if (filters.size) params = params.set('size', String(filters.size));
  return params;
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
    let params = new HttpParams()
      .set('related_entity_type', entityType)
      .set('related_entity_id', entityId);
    if (status) params = params.set('status', status);
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
