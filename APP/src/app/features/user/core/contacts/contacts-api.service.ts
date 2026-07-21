import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import type { components } from '../shared/api-types';
import { FieldDef } from '../shared/dynamic-form/types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams, prefixCustomFilters } from '../shared/services/query-builder';

/**
 * Slim wire shape for `GET /api/v1/contacts` list items.
 *
 * Sourced from the backend-generated OpenAPI types. Any backend
 * change to `ContactListItem` now surfaces here at TS compile time
 * after running `npm run generate:api-types` (see `docs/codegen.md`).
 */
export type ContactListItem = components['schemas']['ContactListItem'];

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
  /**
   * Notes for a contact live in `tbl_activities` rows (type='note')
   * — versioned, authored, queryable. The former single-blob
   * `Contact.notes` column was retired in backend migration 0158.
   * Post via `POST /activities`; render via the Activities tab.
   */
  custom_data: Record<string, unknown>;
  assigned_to_id: string | null;
  last_activity_at: string | null;
  created_at: string;
  updated_at: string;
  /** Step 22 — DPDP opt-in state. */
  whatsapp_opt_in_status?: WhatsAppOptInStatus;
  whatsapp_opt_in_source?: WhatsAppOptInSource | null;
  whatsapp_opt_in_recorded_at?: string | null;
  whatsapp_opt_in_recorded_by_user_id?: string | null;
  whatsapp_opt_out_recorded_at?: string | null;
  whatsapp_opt_out_reason?: string | null;
  /** Campaigns v1 Step 06 — Email opt-in mirror of the WA state
   *  machine. The tracking unsubscribe endpoint + the campaign send
   *  guard read from ``email_opt_in_status``; the legacy
   *  ``email_opt_out`` boolean stays as a fast-path shortcut. */
  email_opt_in_status?: EmailOptInStatus;
  email_opt_in_source?: EmailOptInSource | null;
  email_opt_in_recorded_at?: string | null;
  /** DPDP right-to-be-forgotten stamp. Non-null → PII wiped, both
   *  channels forced to opted_out, row retained so cross-module FKs
   *  don't break. UI must render an "Anonymised" chip instead of the
   *  placeholder full_name. */
  anonymised_at?: string | null;
}

/** Step 22 — DPDP opt-in state machine. Mirrored from the backend
 *  ``whatsapp_opt_in_status`` ENUM. */
export type WhatsAppOptInStatus = 'never_contacted' | 'implicit' | 'opted_in' | 'opted_out';

export type WhatsAppOptInSource =
  | 'form_widget'
  | 'bulk_import'
  | 'manual_entry'
  | 'inbound_first_message'
  | 'explicit_opt_in_link'
  | 'stop_keyword';

/** Campaigns v1 Step 06 — Email opt-in state machine (mirror of WA). */
export type EmailOptInStatus = 'never_contacted' | 'implicit' | 'opted_in' | 'opted_out';

export type EmailOptInSource =
  | 'form_widget'
  | 'bulk_import'
  | 'manual_entry'
  | 'inbound_first_message'
  | 'explicit_opt_in_link'
  | 'email_unsubscribe_link'
  | 'bounce_hard'
  | 'manual_override';

export interface ConsentEvent {
  id: string;
  channel: string;
  old_status: WhatsAppOptInStatus | null;
  new_status: WhatsAppOptInStatus;
  source: WhatsAppOptInSource | null;
  actor_user_id: string | null;
  ip_address: string | null;
  reason: string | null;
  recorded_at: string;
}

export interface OptInHistory {
  contact_id: string;
  status: WhatsAppOptInStatus;
  source: WhatsAppOptInSource | null;
  recorded_at: string | null;
  recorded_by_user_id: string | null;
  opt_out_recorded_at: string | null;
  opt_out_reason: string | null;
  events: ConsentEvent[];
}

export interface ContactCreate {
  full_name: string;
  phone?: string | null;
  email?: string | null;
  source?: string | null;
  tags?: string[];
  // `notes` was retired — post a note via /activities after create.
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
export type ContactFieldTarget = 'full_name' | 'phone' | 'email' | 'source' | 'tag' | 'skip';

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
  /** DPDP opt-in provenance picked on the wizard's mapping step.
   *  Backend Step 0164 persists it onto every contact this import
   *  inserts (whatsapp_opt_in_status='opted_in' + source=…). */
  opt_in_source?: WhatsAppOptInSource | null;
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
export class ContactsApiService extends BaseCrudApiService<Contact, ContactCreate, ContactUpdate> {
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
  reassign(id: string, body: { userId: string | null; note?: string | null }): Observable<Contact> {
    return this.http.post<Contact>(`${this.base}/${id}/reassign`, {
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  /** DPDP right-to-be-forgotten. Wipes PII on the contact row +
   *  force-flips both consent channels to opted_out. Historical FKs
   *  (activities, leads, appointments, invoices) are preserved. The
   *  operator-supplied `reason` is written to the audit log for
   *  future auditor trace. */
  anonymise(id: string, reason: string | null): Observable<Contact> {
    return this.http.post<Contact>(`${this.base}/${id}/anonymise`, {
      reason: reason ?? null,
    });
  }

  /** Fold `secondaryId` into `primaryId` and delete the secondary.
   *  Every FK / polymorphic ref that pointed at the secondary is
   *  repointed at the primary (activities, tasks, leads, appointments,
   *  calls, conversations, campaign messages, consent events, workflow
   *  runs, group memberships, ...). Returns the refreshed primary +
   *  a per-table count of rows reassigned. */
  merge(
    primaryId: string,
    secondaryId: string,
  ): Observable<{
    primary: Contact;
    secondary_id: string;
    rows_reassigned: Record<string, number>;
  }> {
    return this.http.post<{
      primary: Contact;
      secondary_id: string;
      rows_reassigned: Record<string, number>;
    }>(`${this.base}/${primaryId}/merge`, { secondary_id: secondaryId });
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

  /** Bulk-hydrate `ContactListItem`s by id. Used by list pages that
   *  render contact summaries per row (walk-ins, appointments) to
   *  collapse per-row `GET /contacts/{id}` fan-outs into one call. */
  hydrateByIds(ids: string[]): Observable<ContactListItem[]> {
    return this.http.post<ContactListItem[]>(`${this.base}/hydrate`, { ids });
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
    return this.http.get<{ matches: ContactDuplicateMatch[] }>(`${this.base}/check-duplicate`, {
      params,
    });
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

  /** Create a contact from an indirect entry point (e.g. the lead-form
   * auto-create) where the operator can't reasonably fill required
   * custom fields. Backend skips the required-custom-field check, same
   * as widget / webhook ingest paths. */
  createStub(payload: ContactCreate): Observable<Contact> {
    return this.http.post<Contact>(this.base, payload, {
      params: { stub: 'true' },
    });
  }

  /** Step 22 — DPDP opt-in surface. Read returns current state +
   *  immutable consent-log history for the contact-detail panel.
   *  Read gates on `contacts.read`; writes gate on
   *  `whatsapp.opt_in.manage` (server-side; junior roles get 403). */
  getOptIn(contactId: string): Observable<OptInHistory> {
    return this.http.get<OptInHistory>(`${this.base}/${contactId}/opt-in`);
  }

  /** Manual opt-in override. ``source`` must match one of the backend
   *  enum values; the contact-detail UI defaults to `'manual_entry'`. */
  recordOptIn(
    contactId: string,
    body: {
      source: WhatsAppOptInSource;
      reason?: string | null;
      request_evidence?: Record<string, unknown>;
    },
  ): Observable<ConsentEvent> {
    return this.http.post<ConsentEvent>(`${this.base}/${contactId}/opt-in`, body);
  }

  /** Manual opt-out override. Source is always `manual_entry` on this
   *  path; auto-flips from STOP keyword come through the webhook. */
  recordOptOut(
    contactId: string,
    body: {
      reason?: string | null;
      request_evidence?: Record<string, unknown>;
    },
  ): Observable<ConsentEvent> {
    return this.http.post<ConsentEvent>(`${this.base}/${contactId}/opt-out`, body);
  }

  /** Step 1 of bulk import: stream the file to the backend, get back
   * the import id + detected headers + suggested column mapping. */
  uploadImport(file: File): Observable<ContactImportUploadOut> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<ContactImportUploadOut>(`${this.base}/imports/upload`, form);
  }

  /** Step 2 of bulk import: preview what commit would do without
   * touching the contacts table. Returns dupe + skip + error counts. */
  dryRunImport(importId: string, body: ContactImportRunIn): Observable<ContactImportDryRunOut> {
    return this.http.post<ContactImportDryRunOut>(`${this.base}/imports/${importId}/dry-run`, body);
  }

  /** Step 3 of bulk import: write the contacts. Backend is idempotent
   * on `importId` so re-clicks don't double-insert. */
  commitImport(importId: string, body: ContactImportRunIn): Observable<ContactImportCommitOut> {
    return this.http.post<ContactImportCommitOut>(`${this.base}/imports/${importId}/commit`, body);
  }
}
