import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { Contact } from '../contacts/contacts-api.service';
import { FieldDef } from '../shared/dynamic-form/types';
import { buildHttpParams } from '../shared/services/query-builder';

export type WalkInStatus =
  | 'browsing'
  | 'interested'
  | 'follow_up'
  | 'converted'
  | 'left';

export interface WalkIn {
  id: string;
  org_id: string;
  contact_id: string;
  time_in: string;
  time_out: string | null;
  duration_min: string | null;
  requirement: string | null;
  budget: string | null;
  assigned_to_id: string | null;
  status: WalkInStatus;
  notes: string | null;
  custom_data: Record<string, unknown>;
  last_activity_at: string | null;
  linked_lead_id: string | null;
  created_at: string;
  updated_at: string;
}

export type WalkInSortKey = 'time_in' | 'created_at' | 'last_activity_at';
export type SortOrder = 'asc' | 'desc';

export interface WalkInUpdate {
  requirement?: string | null;
  budget?: string | null;
  assigned_to_id?: string | null;
  status?: WalkInStatus;
  notes?: string | null;
  custom_data?: Record<string, unknown>;
}

export interface QuickRegisterPayload {
  phone: string;
  full_name: string;
  email?: string | null;
  source?: string | null;
  requirement?: string | null;
  budget?: string | null;
  assigned_to_id?: string | null;
  notes?: string | null;
  custom_data?: Record<string, unknown>;
}

export interface QuickRegisterResponse {
  walk_in: WalkIn;
  contact: Contact;
  contact_was_created: boolean;
}

export interface WalkInListQuery {
  status?: WalkInStatus;
  assigned_to?: string | null;
  open_only?: boolean;
  date_from?: string;
  date_to?: string;
  sort?: WalkInSortKey;
  order?: SortOrder;
  page?: number;
  size?: number;
}

@Injectable({ providedIn: 'root' })
export class WalkInsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/walk-ins`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/walk_in/render`;

  list(query: WalkInListQuery = {}): Observable<WalkIn[]> {
    const params = buildHttpParams({
      status: query.status,
      assigned_to: query.assigned_to,
      open_only: query.open_only ? query.open_only : undefined,
      date_from: query.date_from,
      date_to: query.date_to,
      sort: query.sort,
      order: query.order,
      page: query.page,
      size: query.size,
    });
    return this.http.get<WalkIn[]>(this.base, { params });
  }

  get(id: string): Observable<WalkIn> {
    return this.http.get<WalkIn>(`${this.base}/${id}`);
  }

  update(id: string, payload: WalkInUpdate): Observable<WalkIn> {
    return this.http.patch<WalkIn>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  checkout(id: string): Observable<WalkIn> {
    return this.http.patch<WalkIn>(`${this.base}/${id}/checkout`, {});
  }

  quickRegister(payload: QuickRegisterPayload): Observable<QuickRegisterResponse> {
    return this.http.post<QuickRegisterResponse>(
      `${this.base}/quick-register`,
      payload,
    );
  }

  /** Single-row reassign. `userId === null` clears the owner. */
  reassign(
    id: string,
    body: { userId: string | null; note?: string | null },
  ): Observable<WalkIn> {
    return this.http.post<WalkIn>(`${this.base}/${id}/reassign`, {
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

  bulkCheckout(
    ids: string[],
  ): Observable<{ checked_out: number; already_checked_out: number }> {
    return this.http.post<{
      checked_out: number;
      already_checked_out: number;
    }>(`${this.base}/bulk-checkout`, { ids });
  }

  /** Walk-in → Lead conversion. Returns ids of the touched rows so
   * the caller can deep-link to the new lead. 409 if already converted. */
  convert(
    id: string,
    body: {
      contact_link_mode?: 'auto' | 'link';
      linked_contact_id?: string | null;
      notes?: string | null;
    } = {},
  ): Observable<{ walk_in_id: string; contact_id: string; lead_id: string }> {
    return this.http.post<{
      walk_in_id: string;
      contact_id: string;
      lead_id: string;
    }>(`${this.base}/${id}/convert`, {
      contact_link_mode: body.contact_link_mode ?? 'auto',
      linked_contact_id: body.linked_contact_id ?? null,
      notes: body.notes ?? null,
    });
  }

  /** Field defs for `entity_type='walk_in'` — feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }
}
