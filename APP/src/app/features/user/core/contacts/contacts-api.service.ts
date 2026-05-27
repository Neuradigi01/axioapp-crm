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
  assigned_to_id: string | null;
  last_activity_at: string | null;
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
  assigned_to_id: string | null;
  last_activity_at: string | null;
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
  assigned_to_id?: string | null;
}

export type ContactUpdate = Partial<ContactCreate>;

export type ContactSortKey = 'full_name' | 'created_at' | 'last_activity_at';
export type SortOrder = 'asc' | 'desc';

/** Wire shape for `GET /contacts/check-duplicate`. Slim — used by the
 * create / edit modal to render a "view existing" banner without a
 * second round-trip. */
export interface ContactDuplicateMatch {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
}

export interface ContactListQuery {
  q?: string;
  source?: string;
  tag?: string;
  /** Owner UUID. Pass undefined to skip the filter. */
  assigned_to_id?: string | null;
  sort?: ContactSortKey;
  order?: SortOrder;
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
    if (query.assigned_to_id) {
      params = params.set('assigned_to_id', query.assigned_to_id);
    }
    if (query.sort) params = params.set('sort', query.sort);
    if (query.order) params = params.set('order', query.order);
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

  /** Single-row reassign. `userId === null` clears the owner. */
  reassign(
    id: string,
    body: { userId: string | null; note?: string | null },
  ): Observable<Contact> {
    return this.http.post<Contact>(`${this.base}/${id}/reassign`, {
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  bulkReassign(
    ids: string[],
    body: { userId: string | null; note?: string | null },
  ): Observable<{ reassigned: number }> {
    return this.http.post<{ reassigned: number }>(`${this.base}/bulk-reassign`, {
      ids,
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  bulkDelete(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${this.base}/bulk-delete`, {
      ids,
    });
  }

  bulkAddTag(ids: string[], tag: string): Observable<{ updated: number }> {
    return this.http.post<{ updated: number }>(`${this.base}/bulk-add-tag`, {
      ids,
      tag,
    });
  }

  /** Live duplicate check called from the create / edit modal as the
   * user types. Backend matches phone on last-10-digit suffix and
   * email case-insensitively. */
  checkDuplicate(query: {
    phone?: string | null;
    email?: string | null;
    excludeId?: string | null;
  }): Observable<{ matches: ContactDuplicateMatch[] }> {
    let params = new HttpParams();
    if (query.phone) params = params.set('phone', query.phone);
    if (query.email) params = params.set('email', query.email);
    if (query.excludeId) params = params.set('exclude_id', query.excludeId);
    return this.http.get<{ matches: ContactDuplicateMatch[] }>(
      `${this.base}/check-duplicate`,
      { params },
    );
  }

  /** Streamed CSV download of the current filter. Backend caps at 50k
   * rows (returns 422). The caller is responsible for triggering the
   * browser download via the returned Blob. */
  exportCsv(query: ContactListQuery = {}): Observable<Blob> {
    let params = new HttpParams();
    if (query.q) params = params.set('q', query.q);
    if (query.source) params = params.set('source', query.source);
    if (query.tag) params = params.set('tag', query.tag);
    if (query.assigned_to_id) {
      params = params.set('assigned_to_id', query.assigned_to_id);
    }
    if (query.customFilters) {
      for (const [key, value] of Object.entries(query.customFilters)) {
        if (value !== undefined && value !== '') {
          params = params.set(`custom.${key}`, value);
        }
      }
    }
    return this.http.get(`${this.base}/export.csv`, {
      params,
      responseType: 'blob',
    });
  }

  /** Render-shape custom field defs for the contact dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }
}
