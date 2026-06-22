import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../shared/services/query-builder';

/**
 * WhatsApp template management API client
 * (whatsapp-platform-upgrade Step 9).
 *
 * Mirrors the Step-8 backend at
 * `/api/v1/integrations/whatsapp/templates/manage` — list / create
 * draft / edit / submit-for-approval / duplicate / delete. The
 * legacy `/whatsapp/templates` read endpoint (campaign picker —
 * approved-only) lives in `integrations-api.service.ts` and is
 * intentionally NOT duplicated here.
 */

export type WhatsAppTemplateCategory =
  | 'MARKETING'
  | 'UTILITY'
  | 'AUTHENTICATION';

export type WhatsAppTemplateHeaderType =
  | 'TEXT'
  | 'IMAGE'
  | 'VIDEO'
  | 'DOCUMENT';

export type WhatsAppTemplateSubmissionStatus =
  | 'draft'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'paused'
  | 'disabled';

export type WhatsAppTemplateButtonType =
  | 'QUICK_REPLY'
  | 'URL'
  | 'PHONE_NUMBER';

export interface WhatsAppTemplateButton {
  type: WhatsAppTemplateButtonType;
  text: string;
  url?: string;
  phone_number?: string;
}

export interface WhatsAppTemplateUpsert {
  name: string;
  language: string;
  category: WhatsAppTemplateCategory;
  body: string;
  header_type?: WhatsAppTemplateHeaderType | null;
  header_text?: string | null;
  footer_text?: string | null;
  buttons?: WhatsAppTemplateButton[];
}

export interface WhatsAppTemplateRead {
  id: string;
  name: string;
  language: string;
  category: string;
  status: string;
  body: string;
  header_type: string | null;
  header_text: string | null;
  footer_text: string | null;
  variable_count: number;
  meta_template_id: string | null;
  submission_status: WhatsAppTemplateSubmissionStatus;
  rejection_reason: string | null;
  submitted_by_user_id: string | null;
  submitted_at: string | null;
  body_components: Array<Record<string, unknown>> | null;
  last_synced_at: string;
}

export interface WhatsAppTemplateSubmissionResult {
  id: string;
  submission_status: WhatsAppTemplateSubmissionStatus;
  meta_template_id: string | null;
  meta_status: string | null;
}

export interface ListTemplatesQuery {
  submission_status?: WhatsAppTemplateSubmissionStatus;
  category?: string;
  language?: string;
}


@Injectable({ providedIn: 'root' })
export class WhatsAppTemplatesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/templates/manage`;

  /** List templates with optional filters. Includes drafts — the
   *  management surface needs every lifecycle state visible. */
  list(query: ListTemplatesQuery = {}): Observable<WhatsAppTemplateRead[]> {
    const params = buildHttpParams({
      submission_status: query.submission_status,
      category: query.category,
      language: query.language,
    });
    return this.http.get<WhatsAppTemplateRead[]>(this.base, { params });
  }

  /** Create a new draft template. Meta is NOT called until the
   *  operator hits Submit. */
  create(payload: WhatsAppTemplateUpsert): Observable<WhatsAppTemplateRead> {
    return this.http.post<WhatsAppTemplateRead>(this.base, payload);
  }

  /** Edit a draft / rejected template. Approved / pending rows
   *  reject with 403; the UI offers Duplicate instead. */
  update(
    id: string,
    payload: WhatsAppTemplateUpsert,
  ): Observable<WhatsAppTemplateRead> {
    return this.http.patch<WhatsAppTemplateRead>(`${this.base}/${id}`, payload);
  }

  /** Delete a template — local + Meta (if previously submitted).
   *  Returns 204 No Content. */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Submit a draft to Meta for approval. Server returns the new
   *  Meta-side id + initial status; the row's submission_status
   *  flips to `pending_review`. Approval / rejection arrives via
   *  the message_template_status_update webhook. */
  submit(id: string): Observable<WhatsAppTemplateSubmissionResult> {
    return this.http.post<WhatsAppTemplateSubmissionResult>(
      `${this.base}/${id}/submit`,
      {},
    );
  }

  /** Clone any template into a fresh draft. Name suffix is server-
   *  side (`_copy`, `_copy_2`, …). */
  duplicate(id: string): Observable<WhatsAppTemplateRead> {
    return this.http.post<WhatsAppTemplateRead>(
      `${this.base}/${id}/duplicate`,
      {},
    );
  }
}
