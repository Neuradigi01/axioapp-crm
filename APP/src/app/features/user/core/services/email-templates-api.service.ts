/**
 * Typed HTTP wrappers for the email-templates surface.
 *
 * Endpoints (all under `${apiBaseUrl}/email/templates`):
 *
 *  - `list(filters?)` — paginated GET with optional `q` + `is_active`.
 *  - `get(id)`        — single read; 404 when soft-deleted or absent.
 *  - `create(payload)`— POST; backend runs save-time variable
 *                       validation, derives `body_text` from
 *                       `body_html` when missing.
 *  - `update(id, payload)` — PATCH (partial).
 *  - `delete(id)`     — soft delete (preserves `email_sequence_steps`
 *                       FK references from Step 7).
 *  - `render(id, ctx)`— POST preview render against a real contact +
 *                       optional lead.
 *  - `variables()`    — GET the variable registry (static system
 *                       fields + the org's custom_field_definitions
 *                       for contacts/leads).
 *
 * Auth: global `authInterceptor` injects the JWT; `retryInterceptor`
 * handles transient failures on GETs.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';


export interface EmailTemplate {
  id: string;
  org_id: string;
  name: string;
  subject: string;
  body_html: string;
  body_text: string;
  variables_used: string[];
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}


export interface EmailTemplateListResponse {
  items: EmailTemplate[];
  total: number;
  page: number;
  size: number;
}


export interface EmailTemplateCreatePayload {
  name: string;
  subject: string;
  body_html: string;
  body_text?: string;
  is_active?: boolean;
}


export interface EmailTemplateUpdatePayload {
  name?: string;
  subject?: string;
  body_html?: string;
  body_text?: string;
  is_active?: boolean;
}


export interface EmailTemplateRenderResponse {
  subject: string;
  body_html: string;
  body_text: string;
  variables_used: string[];
}


export interface VariableRegistryEntry {
  path: string;
  label: string;
  category: string;
  source: 'system' | 'custom';
}


@Injectable({ providedIn: 'root' })
export class EmailTemplatesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/email/templates`;

  /** Paginated list. `q` ILIKEs on name; `is_active` toggles between
   *  active-only / inactive-only / all (omit). */
  list(filters?: {
    q?: string;
    is_active?: boolean;
    page?: number;
    size?: number;
  }): Observable<EmailTemplateListResponse> {
    let params = new HttpParams();
    if (filters?.q) params = params.set('q', filters.q);
    if (filters?.is_active !== undefined) {
      params = params.set('is_active', String(filters.is_active));
    }
    if (filters?.page) params = params.set('page', String(filters.page));
    if (filters?.size) params = params.set('size', String(filters.size));
    return this.http.get<EmailTemplateListResponse>(this.base, { params });
  }

  get(templateId: string): Observable<EmailTemplate> {
    return this.http.get<EmailTemplate>(`${this.base}/${templateId}`);
  }

  create(payload: EmailTemplateCreatePayload): Observable<EmailTemplate> {
    return this.http.post<EmailTemplate>(this.base, payload);
  }

  update(
    templateId: string,
    payload: EmailTemplateUpdatePayload,
  ): Observable<EmailTemplate> {
    return this.http.patch<EmailTemplate>(
      `${this.base}/${templateId}`,
      payload,
    );
  }

  delete(templateId: string): Observable<EmailTemplate> {
    // Backend soft-deletes — returns the deleted row.
    return this.http.delete<EmailTemplate>(`${this.base}/${templateId}`);
  }

  /** Preview render. `lead_id` is optional; passing one resolves
   *  `lead.*` variables in the template. Missing variables surface
   *  as a 400 with the offending paths listed. */
  render(
    templateId: string,
    ctx: { contactId: string; leadId?: string },
  ): Observable<EmailTemplateRenderResponse> {
    let params = new HttpParams().set('contact_id', ctx.contactId);
    if (ctx.leadId) params = params.set('lead_id', ctx.leadId);
    return this.http.post<EmailTemplateRenderResponse>(
      `${this.base}/${templateId}/render`,
      {},
      { params },
    );
  }

  /** Variable registry — static system fields + the org's custom
   *  field definitions for contacts and leads. The editor sidebar
   *  groups by `category`. */
  variables(): Observable<VariableRegistryEntry[]> {
    return this.http.get<VariableRegistryEntry[]>(
      `${this.base}/variables`,
    );
  }
}
