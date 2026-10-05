import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams } from '../shared/services/query-builder';

export type AppointmentStatus = 'scheduled' | 'completed' | 'cancelled' | 'no_show';

/** Display labels for appointment statuses (raw values are snake_case). */
export const APPOINTMENT_STATUS_LABELS: Record<AppointmentStatus, string> = {
  scheduled: 'Scheduled',
  completed: 'Completed',
  cancelled: 'Cancelled',
  no_show: 'No-show',
};

export type AppointmentSortKey = 'scheduled_at' | 'created_at' | 'last_activity_at';

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
  // tasks/google-calendar-sync Step 1 — per-appointment Google-side
  // identifiers. Nullable: unset until Step 4's sync task mirrors the
  // appointment into the assignee's Google Calendar (or when the
  // assignee never connected Calendar).
  google_calendar_event_id?: string | null;
  google_calendar_etag?: string | null;
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
  /** Page size for the open-ended list view; omit for calendar windows. */
  limit?: number;
  offset?: number;
}

@Injectable({ providedIn: 'root' })
export class AppointmentsApiService extends BaseCrudApiService<
  Appointment,
  AppointmentCreate,
  AppointmentUpdate
> {
  protected readonly base = `${environment.apiBaseUrl}/appointments`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/appointment/render`;

  /** Field defs for `entity_type='appointment'` — feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

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
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<Appointment[]>(this.base, { params });
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
  reassign(id: string, body: { userId: string; note?: string | null }): Observable<Appointment> {
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
   * Returns `{cancelled, skipped, skipped_by_status}` so the FE can
   * surface an actionable partial-success message ("2 already
   * completed — delete them instead of cancelling") rather than a
   * vague "skipped" count. */
  bulkCancel(
    ids: string[],
    body: { reason?: string | null } = {},
  ): Observable<{
    cancelled: number;
    skipped: number;
    skipped_by_status: Record<string, number>;
  }> {
    return this.http.post<{
      cancelled: number;
      skipped: number;
      skipped_by_status: Record<string, number>;
    }>(`${this.base}/bulk-cancel`, {
      ids,
      reason: body.reason ?? null,
    });
  }

  /** Hard-delete every selected appointment regardless of status —
   *  mirrors the single-row `DELETE /{id}` per row. `deleted` counts
   *  what actually got removed (ids belonging to another org are
   *  silently dropped by the backend's org-scoped hydrate). */
  bulkDelete(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${this.base}/bulk-delete`, { ids });
  }

  /** Batch-fetch appointment rows by id list. Used by list pages that
   *  render appointment context per row (e.g. the furniture pack's
   *  field-ops view) so they don't fan out one ``GET /{id}`` per
   *  appointment. Cap: 200 ids per call (server-side). */
  hydrateByIds(ids: string[]): Observable<Appointment[]> {
    return this.http.post<Appointment[]>(`${this.base}/hydrate`, { ids });
  }
}
