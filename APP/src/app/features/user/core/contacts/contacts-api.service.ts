import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';

/**
 * Wire shape for `GET /api/v1/contacts`. Mirrors `ContactListResponse`
 * from the backend. `items` use the slim `ContactListItem` schema —
 * notes/custom_data are omitted to keep list payloads light.
 */
export interface ContactListItem {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  source: string | null;
  tags: string[];
  created_at: string;
}

export interface ContactListResponse {
  items: ContactListItem[];
  total: number;
  page: number;
  size: number;
}

export interface Contact {
  id: string;
  org_id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  source: string | null;
  tags: string[];
  notes: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContactCreate {
  full_name: string;
  phone?: string | null;
  email?: string | null;
  source?: string | null;
  tags?: string[];
  notes?: string | null;
  custom_data?: Record<string, unknown>;
}

export type ContactUpdate = Partial<ContactCreate>;

export interface ContactListQuery {
  q?: string;
  source?: string;
  tag?: string;
  page?: number;
  size?: number;
  /** `custom.<field_key> = value` filters. */
  customFilters?: Record<string, string>;
}

@Injectable({ providedIn: 'root' })
export class ContactsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/contacts`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/contact/render`;

  list(query: ContactListQuery = {}): Observable<ContactListResponse> {
    let params = new HttpParams();
    if (query.q) params = params.set('q', query.q);
    if (query.source) params = params.set('source', query.source);
    if (query.tag) params = params.set('tag', query.tag);
    if (query.page) params = params.set('page', String(query.page));
    if (query.size) params = params.set('size', String(query.size));
    if (query.customFilters) {
      for (const [key, value] of Object.entries(query.customFilters)) {
        if (value !== undefined && value !== '') {
          params = params.set(`custom.${key}`, value);
        }
      }
    }
    return this.http.get<ContactListResponse>(this.base, { params });
  }

  get(id: string): Observable<Contact> {
    return this.http.get<Contact>(`${this.base}/${id}`);
  }

  create(payload: ContactCreate): Observable<Contact> {
    return this.http.post<Contact>(this.base, payload);
  }

  update(id: string, payload: ContactUpdate): Observable<Contact> {
    return this.http.patch<Contact>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Render-shape custom field defs for the contact dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }
}
