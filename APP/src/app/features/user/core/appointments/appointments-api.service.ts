import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

export type AppointmentStatus =
  | 'scheduled'
  | 'completed'
  | 'cancelled'
  | 'no_show';

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

export interface AppointmentRangeQuery {
  /** ISO timestamps; backend expects `from` / `to` query params. */
  fromIso: string;
  toIso: string;
  assignedTo?: string;
  status?: AppointmentStatus;
}

@Injectable({ providedIn: 'root' })
export class AppointmentsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/appointments`;

  /** Calendar listing — returns a plain array sorted by scheduled_at. */
  listRange(query: AppointmentRangeQuery): Observable<Appointment[]> {
    let params = new HttpParams()
      .set('from', query.fromIso)
      .set('to', query.toIso);
    if (query.assignedTo) params = params.set('assigned_to', query.assignedTo);
    if (query.status) params = params.set('status', query.status);
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
}
