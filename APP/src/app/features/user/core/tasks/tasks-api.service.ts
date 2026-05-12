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

  /** Caller's own tasks (header popover). */
  listMine(status?: TaskStatus): Observable<TaskListResponse> {
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    return this.http.get<TaskListResponse>(`${this.base}/me`, { params });
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
}
