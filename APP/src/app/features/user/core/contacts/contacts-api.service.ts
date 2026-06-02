import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams, prefixCustomFilters } from '../shared/services/query-builder';

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

/** Targets the operator can map a CSV column to. Mirrors the
 * `ContactFieldTarget` literal in the backend schemas — keep both
 * lists in sync. */
export type ContactFieldTarget =
  | 'full_name'
  | 'phone'
  | 'email'
  | 'source'
  | 'tag'
  | 'skip';

/** Response from `POST /contacts/imports/upload`. */
export interface ContactImportUploadOut {
  id: string;
  filename: string;
  row_count: number;
  headers: string[];
  /** Backend's first-pass column → field guess; UI starts from this. */
  suggested_mapping: Record<string, ContactFieldTarget>;
  sample_rows: Record<string, unknown>[];
}

/** Body for `POST /contacts/imports/{id}/dry-run` and `/commit`. */
export interface ContactImportRunIn {
  mapping: Record<string, ContactFieldTarget>;
  create_group: boolean;
  group_name?: string | null;
}

export interface ContactImportRowError {
  row: number;
  reason: string;
}

/** Response from `POST /contacts/imports/{id}/dry-run`. */
export interface ContactImportDryRunOut {
  will_insert: number;
  will_skip: number;
  duplicate_phone: number;
  errors: ContactImportRowError[];
}

/** Response from `POST /contacts/imports/{id}/commit`. */
export interface ContactImportCommitOut {
  id: string;
  status: string;
  row_count: number;
  success_count: number;
  error_count: number;
  created_group_id: string | null;
}

@Injectable({ providedIn: 'root' })
export class ContactsApiService extends BaseCrudApiService<
  Contact,
  ContactCreate,
  ContactUpdate
> {
  protected readonly base = `${environment.apiBaseUrl}/contacts`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/contact/render`;

  list(query: ContactListQuery = {}): Observable<ContactListResponse> {
    const params = buildHttpParams({
      q: query.q,
      source: query.source,
      tag: query.tag,
      assigned_to_id: query.assigned_to_id,
      sort: query.sort,
      order: query.order,
      page: query.page,
      size: query.size,
      ...prefixCustomFilters(query.customFilters),
    });
    return this.http.get<ContactListResponse>(this.base, { params });
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
    const params = buildHttpParams({
      phone: query.phone,
      email: query.email,
      exclude_id: query.excludeId,
    });
    return this.http.get<{ matches: ContactDuplicateMatch[] }>(
      `${this.base}/check-duplicate`,
      { params },
    );
  }

  /** Streamed CSV download of the current filter. Backend caps at 50k
   * rows (returns 422). The caller is responsible for triggering the
   * browser download via the returned Blob. */
  exportCsv(query: ContactListQuery = {}): Observable<Blob> {
    const params = buildHttpParams({
      q: query.q,
      source: query.source,
      tag: query.tag,
      assigned_to_id: query.assigned_to_id,
      ...prefixCustomFilters(query.customFilters),
    });
    return this.http.get(`${this.base}/export.csv`, {
      params,
      responseType: 'blob',
    });
  }

  /** Render-shape custom field defs for the contact dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

  /** Step 1 of bulk import: stream the file to the backend, get back
   * the import id + detected headers + suggested column mapping. */
  uploadImport(file: File): Observable<ContactImportUploadOut> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<ContactImportUploadOut>(
      `${this.base}/imports/upload`,
      form,
    );
  }

  /** Step 2 of bulk import: preview what commit would do without
   * touching the contacts table. Returns dupe + skip + error counts. */
  dryRunImport(
    importId: string,
    body: ContactImportRunIn,
  ): Observable<ContactImportDryRunOut> {
    return this.http.post<ContactImportDryRunOut>(
      `${this.base}/imports/${importId}/dry-run`,
      body,
    );
  }

  /** Step 3 of bulk import: write the contacts. Backend is idempotent
   * on `importId` so re-clicks don't double-insert. */
  commitImport(
    importId: string,
    body: ContactImportRunIn,
  ): Observable<ContactImportCommitOut> {
    return this.http.post<ContactImportCommitOut>(
      `${this.base}/imports/${importId}/commit`,
      body,
    );
  }
}
