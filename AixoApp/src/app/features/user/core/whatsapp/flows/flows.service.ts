import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type FlowCategory =
  | 'appointment_booking'
  | 'lead_capture'
  | 'feedback'
  | 'signup'
  | 'custom';

export type FlowStatus = 'draft' | 'published' | 'archived';

export interface FlowRow {
  id: string;
  name: string;
  category: FlowCategory;
  status: FlowStatus;
  meta_flow_id: string | null;
  json_definition: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FlowTemplate {
  key: FlowCategory;
  label: string;
  description: string;
}

export interface FlowCreateRequest {
  name: string;
  category: FlowCategory;
  json_definition?: Record<string, unknown> | null;
}

export interface FlowUpdateRequest {
  name?: string | null;
  json_definition?: Record<string, unknown> | null;
}

/**
 * WhatsApp Flows API client (Step 25).
 *
 * All endpoints gate server-side on `whatsapp.flows.manage`; the
 * route guard mirrors the gate so junior staff never see the
 * surface at all.
 */
@Injectable({ providedIn: 'root' })
export class FlowsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/flows`;

  listTemplates(): Observable<FlowTemplate[]> {
    return this.http.get<FlowTemplate[]>(`${this.base}/templates`);
  }

  list(): Observable<FlowRow[]> {
    return this.http.get<FlowRow[]>(this.base);
  }

  get(id: string): Observable<FlowRow> {
    return this.http.get<FlowRow>(`${this.base}/${id}`);
  }

  create(body: FlowCreateRequest): Observable<FlowRow> {
    return this.http.post<FlowRow>(this.base, body);
  }

  update(id: string, body: FlowUpdateRequest): Observable<FlowRow> {
    return this.http.patch<FlowRow>(`${this.base}/${id}`, body);
  }

  publish(id: string): Observable<FlowRow> {
    return this.http.post<FlowRow>(`${this.base}/${id}/publish`, {});
  }

  testSend(id: string, toPhone: string): Observable<unknown> {
    return this.http.post(`${this.base}/${id}/test-send`, {
      to_phone: toPhone,
    });
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
