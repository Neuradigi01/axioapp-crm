/**
 * Typed HTTP wrappers for `/api/v1/contact-groups` (Step 3.5.7 backend).
 *
 * Used by:
 *   - `groups-list.page` (Step 3.5.8) — list + delete + create
 *   - `group-edit.page` (Step 3.5.8)  — create + update + detail
 *   - Campaign audience builder (Step 3.5.9) — list + preview-size
 *
 * All endpoints are gated server-side by `contacts.read` (reads) or
 * `contacts.write` (mutations). The Settings UI hides the action
 * buttons for users without the write permission; the API still
 * enforces it (defence in depth).
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../shared/services/query-builder';

export interface GroupFilter {
  q?: string;
  source?: string;
  tag?: string;
  /** Forward-compat: future filter keys land here (backend's JSONB
   *  column accepts `extra='allow'`). */
  [key: string]: string | undefined;
}

export interface ContactGroup {
  id: string;
  name: string;
  description: string | null;
  is_dynamic: boolean;
  filter_json: GroupFilter | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  /** Attached by the list endpoint via a per-row COUNT — `null`
   *  if the backend skipped it (shouldn't happen in v1, but the
   *  schema declares it optional). */
  member_count: number | null;
}

export interface ContactGroupDetail extends ContactGroup {
  /** First 10 contact ids for the edit-page preview. Full member
   *  list pagination is deferred to a future endpoint if needed. */
  sample_contact_ids: string[];
}

export interface ContactGroupListResponse {
  items: ContactGroup[];
  total: number;
  page: number;
  size: number;
}

export interface ContactGroupCreate {
  name: string;
  description?: string | null;
  is_dynamic: boolean;
  /** Required when `is_dynamic=true`; must be omitted otherwise. */
  filter_json?: GroupFilter | null;
  /** Required when `is_dynamic=false`; must be omitted otherwise.
   *  Empty `[]` is legal — creates a zero-member static group. */
  contact_ids?: string[] | null;
}

export interface ContactGroupUpdate {
  name?: string;
  description?: string | null;
  /** Allowed only on dynamic groups. */
  filter_json?: GroupFilter | null;
  /** Allowed only on static groups. Fully replaces the member set. */
  contact_ids?: string[] | null;
}

export interface PreviewSizeIn {
  /** Exactly one of `filter_json` or `group_id` — backend rejects
   *  both/neither with 422. */
  filter_json?: GroupFilter;
  group_id?: string;
}

export interface PreviewSizeOut {
  count: number;
}

@Injectable({ providedIn: 'root' })
export class ContactGroupsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/contact-groups`;

  list(page: number = 1, size: number = 50): Observable<ContactGroupListResponse> {
    const params = buildHttpParams({ page, size });
    return this.http.get<ContactGroupListResponse>(this.base, { params });
  }

  get(id: string): Observable<ContactGroupDetail> {
    return this.http.get<ContactGroupDetail>(`${this.base}/${id}`);
  }

  create(payload: ContactGroupCreate): Observable<ContactGroup> {
    return this.http.post<ContactGroup>(this.base, payload);
  }

  update(id: string, payload: ContactGroupUpdate): Observable<ContactGroup> {
    return this.http.patch<ContactGroup>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  previewSize(payload: PreviewSizeIn): Observable<PreviewSizeOut> {
    return this.http.post<PreviewSizeOut>(`${this.base}/preview-size`, payload);
  }
}
