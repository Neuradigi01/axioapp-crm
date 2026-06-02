import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

export type AppointmentStatus =
  | 'scheduled'
  | 'completed'
  | 'cancelled'
  | 'no_show';

export type AppointmentSortKey =
  | 'scheduled_at'
  | 'created_at'
  | 'last_activity_at';

export type SortOrder = 'asc' | 'desc';

export interface Appointment {
  id: string;
  org_id: string;
  contact_id: string;
  title: string;
  purpose: string | null;
  scheduled_at: string;
  duration_min: number;
  location: string | null;
  status: AppointmentStatus;
  assigned_to_id: string;
  custom_data: Record<string, unknown>;
  last_activity_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppointmentCreate {
  contact_id: string;
  title: string;
  purpose?: string | null;
  scheduled_at: string;
  duration_min: number;
  location?: string | null;
  assigned_to_id: string;
  custom_data?: Record<string, unknown>;
}

export type AppointmentUpdate = Partial<{
  title: string;
  purpose: string | null;
  scheduled_at: string;
  duration_min: number;
  location: string | null;
  status: AppointmentStatus;
  assigned_to_id: string;
  custom_data: Record<string, unknown>;
}>;

/** Shape the backend returns inside a 409 conflict body. */
export interface ConflictBody {
  success: false;
  message: string;
  conflicts: string[];
}

export interface AppointmentListQuery {
  /** ISO timestamps; backend expects `from` / `to` query params. */
  scheduledFrom?: string;
  scheduledTo?: string;
  assignedTo?: string;
  status?: AppointmentStatus;
  sort?: AppointmentSortKey;
  order?: SortOrder;
}

@Injectable({ providedIn: 'root' })
export class AppointmentsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/appointments`;

  /** Listing — works for both calendar (passes from/to) and list view
   * (omits from/to, applies sort/order/status/assignee). */
  list(query: AppointmentListQuery = {}): Observable<Appointment[]> {
    const params = buildHttpParams({
      from: query.scheduledFrom,
      to: query.scheduledTo,
      assigned_to: query.assignedTo,
      status: query.status,
      sort: query.sort,
      order: query.order,
    });
    return this.http.get<Appointment[]>(this.base, { params });
  }

  get(id: string): Observable<Appointment> {
    return this.http.get<Appointment>(`${this.base}/${id}`);
  }

  create(payload: AppointmentCreate): Observable<Appointment> {
    return this.http.post<Appointment>(this.base, payload);
  }

  update(id: string, payload: AppointmentUpdate): Observable<Appointment> {
    return this.http.patch<Appointment>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Shift an appointment's slot without going through the full edit
   * form. Server writes a dedicated `reschedule` audit activity. */
  reschedule(
    id: string,
    body: { scheduledAt: string; reason?: string | null },
  ): Observable<Appointment> {
    return this.http.post<Appointment>(`${this.base}/${id}/reschedule`, {
      scheduled_at: body.scheduledAt,
      reason: body.reason ?? null,
    });
  }

  /** Single-row reassign. Appointments require an owner, so `userId`
   * must be non-null — the backend rejects null. */
  reassign(
    id: string,
    body: { userId: string; note?: string | null },
  ): Observable<Appointment> {
    return this.http.post<Appointment>(`${this.base}/${id}/reassign`, {
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

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

  /** Bulk-cancel — rows not currently in `scheduled` are skipped.
   * Returns `{cancelled, skipped}` so the FE can surface the
   * partial-success split. */
  bulkCancel(
    ids: string[],
    body: { reason?: string | null } = {},
  ): Observable<{ cancelled: number; skipped: number }> {
    return this.http.post<{ cancelled: number; skipped: number }>(
      `${this.base}/bulk-cancel`,
      { ids, reason: body.reason ?? null },
    );
  }
}
