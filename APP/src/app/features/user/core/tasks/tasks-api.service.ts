import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { buildHttpParams } from '../shared/services/query-builder';

/**
 * Mirrors `TaskStatus` / `TaskPriority` / `TaskFollowupType` from the
 * backend. Keep these unions in sync with
 * `api/src/app/core/tasks/models.py` — new values here without the
 * backend enum will be rejected at HTTP boundary.
 */
export type TaskStatus = 'open' | 'done' | 'cancelled' | 'missed';
export type TaskPriority = 'low' | 'med' | 'high';
/** T3 — the enum backend already has. Was previously not on the FE at all. */
export type TaskFollowupType = 'call' | 'whatsapp' | 'email' | 'document' | 'meeting' | 'other';

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: 'Low',
  med: 'Medium',
  high: 'High',
};

export const TASK_FOLLOWUP_LABELS: Record<TaskFollowupType, string> = {
  call: 'Call',
  whatsapp: 'WhatsApp',
  email: 'Email',
  document: 'Document',
  meeting: 'Meeting',
  other: 'Other',
};

/** `GET /tasks/me/counts` · `/tasks/all/counts` — headline numbers. */
export interface TaskCounts {
  open: number;
  overdue: number;
  due_today: number;
  done: number;
  missed: number;
}
export type TaskDueFilter = 'today' | 'overdue' | 'upcoming';
export type TaskSortBy = 'due_at' | 'priority' | 'title' | 'created_at' | 'last_activity_at';
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
  /** Linked contact's name (a lead shows its contact's). List endpoints
   *  only; null when the linked record no longer exists. */
  related_label?: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  /** T3 — the touchpoint channel type. Nullable = generic to-do. */
  followup_type: TaskFollowupType | null;
  last_activity_at: string | null;
  /** T4 — dynamic per-org custom field payload. */
  custom_data: Record<string, unknown>;
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
  followup_type?: TaskFollowupType | null;
  custom_data?: Record<string, unknown>;
}

export type TaskUpdate = Partial<{
  title: string;
  description: string | null;
  due_at: string | null;
  assigned_to_id: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  followup_type: TaskFollowupType | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  custom_data: Record<string, unknown>;
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
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/task/render`;

  /** T4 — Field defs for `entity_type='task'`; feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

  /** T1 — Terminal transition to `missed`. Backend refuses if the task
   *  isn't `open`; caller shows a toast either way. */
  markMissed(id: string): Observable<Task> {
    return this.http.post<Task>(`${this.base}/${id}/mark-missed`, {});
  }

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

  /** Headline counts for the caller's own tasks. */
  countsMine(): Observable<TaskCounts> {
    return this.http.get<TaskCounts>(`${this.base}/me/counts`);
  }

  /** Org-wide headline counts (requires `users.read`), optionally for one owner. */
  countsAll(assignedToId?: string): Observable<TaskCounts> {
    return this.http.get<TaskCounts>(`${this.base}/all/counts`, {
      params: assignedToId ? { assigned_to_id: assignedToId } : {},
    });
  }

  create(payload: TaskCreate): Observable<Task> {
    return this.http.post<Task>(this.base, payload);
  }

  get(id: string): Observable<Task> {
    return this.http.get<Task>(`${this.base}/${id}`);
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
    return this.http.post<{ reassigned: number }>(`${this.base}/bulk-reassign`, {
      ids,
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  /** Bulk mark-done. Already-done rows are skipped (counted). Returns
   * `{done, skipped}` so the FE can surface partial success. */
  bulkMarkDone(ids: string[]): Observable<{ done: number; skipped: number }> {
    return this.http.post<{ done: number; skipped: number }>(`${this.base}/bulk-mark-done`, {
      ids,
    });
  }

  bulkDelete(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${this.base}/bulk-delete`, {
      ids,
    });
  }
}
