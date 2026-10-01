import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, switchMap, throwError } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

/**
 * Central template library API client.
 *
 * Wraps the Step-3 endpoints at `/api/v1/templates` (tasks/template-library).
 * Read endpoints (`list`, `get`, `versions`, `preview`, `variables`) are
 * `templates.read`-gated server-side; mutations (`create`, `update`,
 * `archive`) plus the workflow transitions and `testSend` need
 * `templates.write` / `templates.review` / `templates.publish`. The
 * page component should ALSO render those buttons behind permission
 * checks so the UI doesn't dangle un-clickable affordances.
 */

export type TemplateChannel = 'email' | 'whatsapp' | 'sms' | 'facebook' | 'instagram' | 'push';

export type TemplateInternalStatus = 'draft' | 'in_review' | 'approved' | 'published' | 'archived';

export type TemplateExternalStatus = 'n_a' | 'pending' | 'approved' | 'rejected' | 'paused';

export type TemplateCategory = 'marketing' | 'transactional' | 'service';

export type WaButtonType = 'url' | 'phone_number' | 'quick_reply';
export type WaHeaderType = 'text' | 'image' | 'video' | 'document';

export interface WhatsAppTemplateButton {
  type: WaButtonType;
  text: string;
  url?: string | null;
  phone_number?: string | null;
}

export type WaCategory = 'marketing' | 'utility' | 'authentication';

export interface WhatsAppExtensionPayload {
  /** Meta's WA category (marketing / utility / authentication) — a
   *  DIFFERENT taxonomy from TemplateCategory (marketing / transactional
   *  / service). Store both: the central column drives the CRM's send
   *  guard, this one drives Meta's review track. */
  category?: WaCategory | null;
  header_type?: WaHeaderType | null;
  header_text?: string | null;
  footer_text?: string | null;
  buttons?: WhatsAppTemplateButton[] | null;
}

export interface WhatsAppExtensionRead {
  category: WaCategory | null;
  header_type: WaHeaderType | null;
  header_text: string | null;
  footer_text: string | null;
  buttons: WhatsAppTemplateButton[] | null;
}

export interface TemplateRead {
  id: string;
  org_id: string;
  channel: TemplateChannel;
  name: string;
  category: TemplateCategory;
  language: string;
  body_text: string;
  /** Campaigns v1 Step 04 — HTML body for Email templates. Null for
   *  every other channel and for Email templates that only ship
   *  plain text. Sanitised server-side on every write. */
  body_html: string | null;
  /** When true, dispatch (Step 05) derives the plain-text fallback
   *  from ``body_html`` if ``body_text`` was left empty. */
  body_text_fallback_auto: boolean;
  subject: string | null;
  preview_text: string | null;
  variables: string[];
  internal_status: TemplateInternalStatus;
  external_status: TemplateExternalStatus;
  /** Campaigns v1 Step 02 — Meta rejection reason surfaced by the list
   *  endpoint (LEFT OUTER JOIN onto the WhatsApp extension). Populated
   *  for rejected WA rows; `null` for every other case. Drives the
   *  library + campaign picker tooltip on the status badge. */
  external_rejection_reason: string | null;
  external_provider_id: string | null;
  current_version: number;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  /** Owner / Admin (or any role with `templates.activate`) can flip
   *  this to false to keep the row in the library but block every
   *  send picker from using it. Defaults true on every new template. */
  is_active: boolean;
  /** Attribution track — most recent review-trail row picked up by the
   *  list + detail endpoints so the SPA can render "Approved by X on Y"
   *  inline without a per-row fetch. `null` when the template has no
   *  review history yet (fresh draft that was never submitted). */
  last_reviewed_by_user_id: string | null;
  last_reviewed_action: string | null;
  last_reviewed_at: string | null;
  /** Reviewer's note on that latest review — the reject / request-
   *  changes reason the author needs to see. */
  last_review_note?: string | null;
  created_at: string;
  updated_at: string;
  /** Populated by the backend for WhatsApp templates that have a
   *  matching row in `tbl_whatsapp_templates`. Null on non-WA channels
   *  and on legacy WA rows created before the extension write path. */
  whatsapp?: WhatsAppExtensionRead | null;
}

export interface TemplateVersionRead {
  id: string;
  template_id: string;
  version: number;
  body_text: string;
  /** Email HTML design snapshot (null for non-email / text-only). */
  body_html: string | null;
  subject: string | null;
  variables: string[];
  changed_by_user_id: string | null;
  changed_at: string;
  change_note: string | null;
}

export interface TemplateReviewRead {
  id: string;
  template_id: string;
  version: number;
  reviewer_user_id: string | null;
  action: 'submit' | 'approve' | 'reject' | 'request_changes' | 'publish' | 'archive';
  note: string | null;
  created_at: string;
}

export interface TemplateTestSendRead {
  id: string;
  template_id: string;
  version: number;
  channel: TemplateChannel;
  sent_to: string;
  sent_by_user_id: string | null;
  channel_message_id: string | null;
  sent_at: string;
}

export interface TemplateListResponse {
  items: TemplateRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface TemplateCreatePayload {
  name: string;
  channel: TemplateChannel;
  category?: TemplateCategory;
  language?: string;
  /** Optional when `channel === 'email'` AND `body_html` is provided —
   *  the backend derives the plain-text fallback via
   *  ``body_text_fallback_auto``. Required for every other channel. */
  body_text?: string | null;
  /** Campaigns v1 Step 04 — HTML body for Email templates. Only
   *  accepted when `channel === 'email'`. Sanitised on the server. */
  body_html?: string | null;
  body_text_fallback_auto?: boolean;
  subject?: string | null;
  preview_text?: string | null;
  /** Meta-specific extras. Only accepted when `channel === 'whatsapp'`;
   *  the backend upserts the tbl_whatsapp_templates extension row. */
  whatsapp?: WhatsAppExtensionPayload | null;
}

export interface TemplateUpdatePayload {
  name?: string;
  category?: TemplateCategory;
  language?: string;
  body_text?: string;
  /** Campaigns v1 Step 04 — HTML body edit; only meaningful when the
   *  underlying template is on the Email channel. */
  body_html?: string | null;
  body_text_fallback_auto?: boolean | null;
  subject?: string | null;
  preview_text?: string | null;
  change_note?: string | null;
  /** Meta-specific extras. See TemplateCreatePayload. */
  whatsapp?: WhatsAppExtensionPayload | null;
}

export interface TemplateListQuery {
  /** Either a single channel or a list — the column-header filter emits
   *  a `string[]`, the toolbar dropdowns pass a scalar, both work
   *  because `buildHttpParams` serializes arrays as repeated keys and
   *  the backend router accepts `list[ConversationChannel] | None`. */
  channel?: TemplateChannel | TemplateChannel[];
  internal_status?: TemplateInternalStatus | TemplateInternalStatus[];
  external_status?: TemplateExternalStatus;
  /** Activation toggle filter. Pickers pass `true` so operators never
   *  see inactive templates; the library page omits the field to
   *  show everything for admin review. */
  is_active?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
  /** `updated` (default) · `created` · `name`. */
  sort?: TemplateSort;
}

export type TemplateSort = 'updated' | 'created' | 'name';

/** Copy name for "Duplicate": WhatsApp names must stay snake_case. */
function copyName(row: TemplateRead, attempt: number): string {
  const n = attempt > 1 ? String(attempt) : '';
  const suffix =
    row.channel === 'whatsapp' ? `_copy${n ? '_' + n : ''}` : ` (copy${n ? ' ' + n : ''})`;
  return row.name.slice(0, 120 - suffix.length) + suffix;
}

/** Everything a template holds, as a create payload for its copy. */
function copyPayload(row: TemplateRead, attempt: number): TemplateCreatePayload {
  const wa = row.whatsapp;
  return {
    name: copyName(row, attempt),
    channel: row.channel,
    category: row.category,
    language: row.language,
    body_text: row.body_text,
    body_html: row.channel === 'email' ? row.body_html : undefined,
    body_text_fallback_auto: row.channel === 'email' ? row.body_text_fallback_auto : undefined,
    subject: row.subject,
    preview_text: row.preview_text,
    whatsapp:
      row.channel === 'whatsapp' && wa
        ? {
            category: wa.category,
            header_type: wa.header_type,
            header_text: wa.header_text,
            footer_text: wa.footer_text,
            buttons: wa.buttons,
          }
        : undefined,
  };
}

/** How many "_copy_N" names to try before giving up on a name clash. */
const MAX_COPY_ATTEMPTS = 5;

export interface VariableDef {
  key: string;
  label: string;
  type: 'string' | 'int' | 'date' | 'currency' | 'url' | 'bool';
  required: boolean;
  default: string | null;
}

export interface PreviewRequest {
  context: Record<string, unknown>;
}

export interface PreviewResponse {
  subject: string | null;
  body: string;
}

export interface WorkflowActionPayload {
  note?: string | null;
}

export interface TestSendPayload {
  recipient: string;
  sample_context?: Record<string, unknown> | null;
}

export type SmsDltContentCategory =
  | 'transactional'
  | 'promotional'
  | 'service_explicit'
  | 'service_implicit';

export type SmsDltTemplateStatus = 'registered' | 'pending' | 'rejected';

export interface SmsDltMetadata {
  dlt_entity_id: string | null;
  dlt_template_id: string | null;
  dlt_content_category: SmsDltContentCategory;
  dlt_header: string | null;
  dlt_principal_entity_id: string | null;
  dlt_template_status: SmsDltTemplateStatus;
  dlt_registered_at: string | null;
  dlt_rejection_reason: string | null;
}

export interface SmsDltMetadataPatch {
  dlt_entity_id?: string | null;
  dlt_template_id?: string | null;
  dlt_content_category?: SmsDltContentCategory;
  dlt_header?: string | null;
  dlt_principal_entity_id?: string | null;
  dlt_template_status?: SmsDltTemplateStatus;
  dlt_rejection_reason?: string | null;
}

@Injectable({ providedIn: 'root' })
export class TemplatesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/templates`;

  list(query: TemplateListQuery = {}): Observable<TemplateListResponse> {
    const params = buildHttpParams({
      channel: query.channel,
      internal_status: query.internal_status,
      external_status: query.external_status,
      is_active: query.is_active,
      q: query.q,
      limit: query.limit,
      offset: query.offset,
      sort: query.sort,
    });
    return this.http.get<TemplateListResponse>(this.base, { params });
  }

  /** `{channel: count}` for the library's channel tabs. */
  counts(includeArchived = false): Observable<Record<string, number>> {
    const params = buildHttpParams({ include_archived: includeArchived || undefined });
    return this.http.get<Record<string, number>>(`${this.base}/counts`, { params });
  }

  /** Create an editable draft copy of a template (body, subject, email
   *  design, WhatsApp header / footer / buttons). Name clashes retry as
   *  `_copy_2`, `_copy_3`, … */
  duplicate(id: string): Observable<TemplateRead> {
    const attempt = (row: TemplateRead, n: number): Observable<TemplateRead> =>
      this.create(copyPayload(row, n)).pipe(
        catchError((err: { status?: number }) =>
          err?.status === 409 && n < MAX_COPY_ATTEMPTS
            ? attempt(row, n + 1)
            : throwError(() => err),
        ),
      );
    return this.get(id).pipe(switchMap((row) => attempt(row, 1)));
  }

  get(id: string): Observable<TemplateRead> {
    return this.http.get<TemplateRead>(`${this.base}/${id}`);
  }

  create(payload: TemplateCreatePayload): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(this.base, payload);
  }

  update(id: string, payload: TemplateUpdatePayload): Observable<TemplateRead> {
    return this.http.patch<TemplateRead>(`${this.base}/${id}`, payload);
  }

  archive(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Flip a template active. Owner/Admin (or any role with
   *  `templates.activate`) — 403 otherwise. Idempotent. */
  activate(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/activate`, {});
  }

  /** Flip a template inactive so every send picker filters it out. */
  deactivate(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/deactivate`, {});
  }

  versions(id: string): Observable<TemplateVersionRead[]> {
    return this.http.get<TemplateVersionRead[]>(`${this.base}/${id}/versions`);
  }

  getVersion(id: string, version: number): Observable<TemplateVersionRead> {
    return this.http.get<TemplateVersionRead>(`${this.base}/${id}/versions/${version}`);
  }

  preview(id: string, payload: PreviewRequest): Observable<PreviewResponse> {
    return this.http.post<PreviewResponse>(`${this.base}/${id}/preview`, payload);
  }

  variables(channel: TemplateChannel): Observable<VariableDef[]> {
    return this.http.get<VariableDef[]>(`${this.base}/variables/${channel}`);
  }

  // --- workflow transitions (Step 4) -----------------------------------

  submit(id: string, payload: WorkflowActionPayload = {}): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/submit`, payload);
  }

  approve(id: string, payload: WorkflowActionPayload = {}): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/approve`, payload);
  }

  reject(id: string, payload: WorkflowActionPayload): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/reject`, payload);
  }

  requestChanges(id: string, payload: WorkflowActionPayload): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/request-changes`, payload);
  }

  publish(id: string, payload: WorkflowActionPayload = {}): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/publish`, payload);
  }

  archiveViaWorkflow(id: string, payload: WorkflowActionPayload = {}): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/archive`, payload);
  }

  // --- test send (Step 5) ----------------------------------------------

  testSend(id: string, payload: TestSendPayload): Observable<TemplateTestSendRead> {
    return this.http.post<TemplateTestSendRead>(`${this.base}/${id}/test-send`, payload);
  }

  // --- external submission (Step 9) -----------------------------------

  /** Submit to Meta. Media-header WhatsApp templates must include a
   *  sample file (image / video / PDF) for Meta's review. */
  submitExternal(id: string, headerSample?: File): Observable<TemplateRead> {
    if (!headerSample) {
      return this.http.post<TemplateRead>(`${this.base}/${id}/submit-external`, {});
    }
    const form = new FormData();
    form.append('header_sample', headerSample, headerSample.name);
    return this.http.post<TemplateRead>(`${this.base}/${id}/submit-external`, form);
  }

  externalStatus(id: string): Observable<{
    status: string;
    rejection_reason: string | null;
    last_synced_at: string | null;
  }> {
    return this.http.get<{
      status: string;
      rejection_reason: string | null;
      last_synced_at: string | null;
    }>(`${this.base}/${id}/external-status`);
  }

  /** Step 14 — "Resubmit" affordance for templates Meta rejected.
   *  Backend resets `internal_status='draft'` + `external_status='n_a'`
   *  so the operator can edit the body and re-submit. */
  resubmit(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/resubmit`, {});
  }

  // --- SMS DLT metadata (Step 12) -------------------------------------

  getSmsMetadata(id: string): Observable<SmsDltMetadata> {
    return this.http.get<SmsDltMetadata>(`${this.base}/${id}/sms-metadata`);
  }

  patchSmsMetadata(id: string, payload: SmsDltMetadataPatch): Observable<SmsDltMetadata> {
    return this.http.patch<SmsDltMetadata>(`${this.base}/${id}/sms-metadata`, payload);
  }
}
