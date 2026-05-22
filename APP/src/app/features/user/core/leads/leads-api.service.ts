import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';

export type LeadStatus = 'active' | 'won' | 'lost';

/** Provenance of a lead row. Matches the backend `lead_source` PG enum
 * exactly — keep in sync. */
export type LeadSource =
  | 'manual'
  | 'bulk_import'
  | 'widget'
  | 'google_ads'
  | 'meta_ads';

export interface Lead {
  id: string;
  org_id: string;
  contact_id: string;
  pipeline_stage: string;
  status: LeadStatus;
  source: LeadSource;
  assigned_to_id: string | null;
  budget: string | null;
  expected_close_date: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Index signature so `Lead` is structurally compatible with `PipelineItem`. */
  [key: string]: unknown;
}

export interface LeadListResponse {
  items: Lead[];
  total: number;
  page: number;
  size: number;
}

export interface LeadCreate {
  contact_id: string;
  pipeline_stage?: string | null;
  assigned_to_id?: string | null;
  budget?: string | null;
  expected_close_date?: string | null;
  custom_data?: Record<string, unknown>;
  /** Defaults to 'manual' server-side when omitted. */
  source?: LeadSource;
}

export type LeadUpdate = Partial<{
  contact_id: string;
  assigned_to_id: string | null;
  budget: string | null;
  expected_close_date: string | null;
  custom_data: Record<string, unknown>;
}>;

export interface LeadListQuery {
  stage?: string;
  status?: LeadStatus;
  assigned_to?: string;
  q?: string;
  source?: string;
  page?: number;
  size?: number;
  customFilters?: Record<string, string>;
}

@Injectable({ providedIn: 'root' })
export class LeadsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/leads`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/lead/render`;

  list(query: LeadListQuery = {}): Observable<LeadListResponse> {
    let params = new HttpParams();
    if (query.stage) params = params.set('stage', query.stage);
    if (query.status) params = params.set('status', query.status);
    if (query.assigned_to) params = params.set('assigned_to', query.assigned_to);
    if (query.q) params = params.set('q', query.q);
    if (query.source) params = params.set('source', query.source);
    if (query.page) params = params.set('page', String(query.page));
    if (query.size) params = params.set('size', String(query.size));
    if (query.customFilters) {
      for (const [k, v] of Object.entries(query.customFilters)) {
        if (v) params = params.set(`custom.${k}`, v);
      }
    }
    return this.http.get<LeadListResponse>(this.base, { params });
  }

  get(id: string): Observable<Lead> {
    return this.http.get<Lead>(`${this.base}/${id}`);
  }

  create(payload: LeadCreate): Observable<Lead> {
    return this.http.post<Lead>(this.base, payload);
  }

  update(id: string, payload: LeadUpdate): Observable<Lead> {
    return this.http.patch<Lead>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  moveStage(id: string, toStage: string): Observable<Lead> {
    return this.http.post<Lead>(`${this.base}/${id}/move-stage`, {
      to_stage: toStage,
    });
  }

  /** Field defs for `entity_type='lead'` — feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }
}
