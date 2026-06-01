import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { FilterDsl, isEmptyFilter } from '../shared/filter-dsl.types';

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
  /** Operator-defined rule engine output, clamped `[0, 100]`. Surfaced
   * for the Step 6 "Score" column. */
  lead_score: number;
  custom_data: Record<string, unknown>;
  last_activity_at: string | null;
  lost_reason: string | null;
  lost_reason_other: string | null;
  created_at: string;
  updated_at: string;
  /** Index signature so `Lead` is structurally compatible with `PipelineItem`. */
  [key: string]: unknown;
}

export type LeadSortKey =
  | 'created_at'
  | 'last_activity_at'
  | 'lead_score'
  | 'contact_name';
export type SortOrder = 'asc' | 'desc';

/**
 * Paged list response.
 *
 * `total` is `null` when the caller passed `with_total=false` (the
 * backend skips the COUNT(*) in that case for keyset performance).
 * `next_cursor` is `null` when the set is exhausted.
 */
export interface LeadListResponse {
  items: Lead[];
  total: number | null;
  page: number;
  size: number;
  next_cursor: string | null;
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
  lost_reason: string | null;
  lost_reason_other: string | null;
}>;

export interface LeadListQuery {
  stage?: string;
  status?: LeadStatus;
  assigned_to?: string | null;
  q?: string;
  source?: string;
  /** ISO timestamps for the no-activity chip. `lt` returns rows older
   * than the cutoff OR with a NULL `last_activity_at` — the backend
   * treats never-touched leads as "very old" so they surface in the
   * "no activity > N days" filter. */
  last_activity_lt?: string;
  last_activity_gt?: string;
  sort?: LeadSortKey;
  order?: SortOrder;
  /** Offset mode (legacy). When `cursor` is set, page is ignored. */
  page?: number;
  /** Offset-mode page size. Defaults to 50 server-side. */
  size?: number;
  /** Cursor-mode token (opaque base64 from the previous response's
   * `next_cursor`). Pass `null`/omit for the first page. */
  cursor?: string | null;
  /** Cursor-mode limit. Clamped server-side to `[1, 200]`. */
  limit?: number;
  /** Skip the COUNT(*). The list page passes `true` on first page so
   * the footer can show "X of N"; subsequent pages pass `false`. */
  with_total?: boolean;
  customFilters?: Record<string, string>;
  /** Advanced filter DSL (see `shared/filter-dsl.types`). Service
   * JSON-stringifies it into the `filter` query param. */
  filter?: FilterDsl | null;
}

@Injectable({ providedIn: 'root' })
export class LeadsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/leads`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/lead/render`;

  list(query: LeadListQuery = {}): Observable<LeadListResponse> {
    return this.http.get<LeadListResponse>(this.base, {
      params: this.buildParams(query),
    });
  }

  /** Trigger a CSV download for the current filter set. Uses the auth
   * interceptor to attach the bearer token (the browser can't pass
   * `Authorization` headers via a plain `<a download>`), fetches the
   * stream as a blob, then synthesises a download click on a hidden
   * anchor. `query.page`, `size`, `cursor`, and `limit` are dropped —
   * the CSV endpoint always returns the full filtered set up to the
   * server cap. */
  exportCsv(query: LeadListQuery = {}): Observable<Blob> {
    const exportQuery: LeadListQuery = { ...query };
    delete exportQuery.page;
    delete exportQuery.size;
    delete exportQuery.cursor;
    delete exportQuery.limit;
    delete exportQuery.with_total;
    return this.http.get(`${this.base}/export.csv`, {
      params: this.buildParams(exportQuery),
      responseType: 'blob',
    });
  }

  /** Stream a blob to the user as a file download. Handles URL
   * lifecycle (revoke after the click so the GC can reclaim the blob).
   * Filename falls back to "leads.csv" if the caller passes nothing. */
  triggerDownload(blob: Blob, filename = 'leads.csv'): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Slight delay so the browser has a chance to start the download
    // before the URL becomes invalid. 0ms via setTimeout puts it after
    // the current microtask, which is enough.
    setTimeout(() => URL.revokeObjectURL(url), 0);
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

  moveStage(
    id: string,
    toStage: string,
    extras?: { lost_reason?: string | null; lost_reason_other?: string | null },
  ): Observable<Lead> {
    return this.http.post<Lead>(`${this.base}/${id}/move-stage`, {
      to_stage: toStage,
      lost_reason: extras?.lost_reason ?? null,
      lost_reason_other: extras?.lost_reason_other ?? null,
    });
  }

  /** Single-row reassign. `userId === null` clears the owner. */
  reassign(
    id: string,
    body: { userId: string | null; note?: string | null },
  ): Observable<Lead> {
    return this.http.post<Lead>(`${this.base}/${id}/reassign`, {
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

  /** Field defs for `entity_type='lead'` — feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

  private buildParams(query: LeadListQuery): HttpParams {
    let params = new HttpParams();
    if (query.stage) params = params.set('stage', query.stage);
    if (query.status) params = params.set('status', query.status);
    if (query.assigned_to) params = params.set('assigned_to', query.assigned_to);
    if (query.q) params = params.set('q', query.q);
    if (query.source) params = params.set('source', query.source);
    if (query.last_activity_lt) {
      params = params.set('last_activity_lt', query.last_activity_lt);
    }
    if (query.last_activity_gt) {
      params = params.set('last_activity_gt', query.last_activity_gt);
    }
    if (query.sort) params = params.set('sort', query.sort);
    if (query.order) params = params.set('order', query.order);
    if (query.page !== undefined) params = params.set('page', String(query.page));
    if (query.size !== undefined) params = params.set('size', String(query.size));
    if (query.cursor) params = params.set('cursor', query.cursor);
    if (query.limit !== undefined) params = params.set('limit', String(query.limit));
    if (query.with_total !== undefined) {
      params = params.set('with_total', String(query.with_total));
    }
    if (query.filter && !isEmptyFilter(query.filter)) {
      params = params.set('filter', JSON.stringify(query.filter));
    }
    if (query.customFilters) {
      for (const [k, v] of Object.entries(query.customFilters)) {
        if (v) params = params.set(`custom.${k}`, v);
      }
    }
    return params;
  }
}
