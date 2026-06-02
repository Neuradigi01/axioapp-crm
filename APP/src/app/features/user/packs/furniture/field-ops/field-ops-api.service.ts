import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { AppointmentCreate } from '../../../core/appointments/appointments-api.service';
import { buildHttpParams } from '../../../core/shared/services/query-builder';

export type FieldVisitPurpose = 'measurement' | 'installation' | 'inspection';

export interface FieldVisit {
  id: string;
  org_id: string;
  appointment_id: string;
  purpose: FieldVisitPurpose;
  custom_order_id: string | null;
  notes: string | null;
  completed_at: string | null;
  signature_url: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface FieldVisitListResponse {
  items: FieldVisit[];
  total: number;
  page: number;
  size: number;
}

export interface FieldVisitCreate {
  appointment: AppointmentCreate;
  purpose: FieldVisitPurpose;
  custom_order_id?: string | null;
  notes?: string | null;
  custom_data?: Record<string, unknown>;
}

export interface FieldVisitUpdate {
  purpose?: FieldVisitPurpose;
  custom_order_id?: string | null;
  notes?: string | null;
  signature_url?: string | null;
  custom_data?: Record<string, unknown>;
}

export interface MeasurementCopyback {
  item_label: string;
  length_cm?: string | null;
  width_cm?: string | null;
  height_cm?: string | null;
  notes?: string | null;
}

export interface FieldVisitCompletePayload {
  notes?: string | null;
  signature_url?: string | null;
  measurements?: MeasurementCopyback[];
}

export interface FieldVisitPhoto {
  id: string;
  org_id: string;
  visit_id: string;
  url: string;
  caption: string | null;
  taken_at: string | null;
  created_at: string;
}

export interface FieldVisitListQuery {
  assigned_to_id?: string;
  purpose?: FieldVisitPurpose;
  /** `true` = completed only, `false` = open only, undefined = both. */
  completed?: boolean;
  custom_order_id?: string;
  page?: number;
  size?: number;
}

@Injectable({ providedIn: 'root' })
export class FieldOpsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/field-visits`;

  list(query: FieldVisitListQuery = {}): Observable<FieldVisitListResponse> {
    const params = buildHttpParams({
      assigned_to_id: query.assigned_to_id,
      purpose: query.purpose,
      completed: query.completed,
      custom_order_id: query.custom_order_id,
      page: query.page,
      size: query.size,
    });
    return this.http.get<FieldVisitListResponse>(this.base, { params });
  }

  get(id: string): Observable<FieldVisit> {
    return this.http.get<FieldVisit>(`${this.base}/${id}`);
  }

  create(payload: FieldVisitCreate): Observable<FieldVisit> {
    return this.http.post<FieldVisit>(this.base, payload);
  }

  update(id: string, payload: FieldVisitUpdate): Observable<FieldVisit> {
    return this.http.patch<FieldVisit>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  complete(
    id: string,
    payload: FieldVisitCompletePayload,
  ): Observable<FieldVisit> {
    return this.http.post<FieldVisit>(`${this.base}/${id}/complete`, payload);
  }

  listPhotos(id: string): Observable<FieldVisitPhoto[]> {
    return this.http.get<FieldVisitPhoto[]>(`${this.base}/${id}/photos`);
  }

  uploadPhoto(
    id: string,
    file: File,
    caption: string | null,
  ): Observable<FieldVisitPhoto> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (caption) form.append('caption', caption);
    return this.http.post<FieldVisitPhoto>(`${this.base}/${id}/photos`, form);
  }
}
