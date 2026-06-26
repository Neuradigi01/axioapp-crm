import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

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

export type TemplateChannel =
  | 'email'
  | 'whatsapp'
  | 'sms'
  | 'facebook'
  | 'instagram'
  | 'push';

export type TemplateInternalStatus =
  | 'draft'
  | 'in_review'
  | 'approved'
  | 'published'
  | 'archived';

export type TemplateExternalStatus =
  | 'n_a'
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'paused';

export type TemplateCategory =
  | 'marketing'
  | 'transactional'
  | 'service';

export interface TemplateRead {
  id: string;
  org_id: string;
  channel: TemplateChannel;
  name: string;
  category: TemplateCategory;
  language: string;
  body_text: string;
  subject: string | null;
  preview_text: string | null;
  variables: string[];
  internal_status: TemplateInternalStatus;
  external_status: TemplateExternalStatus;
  external_provider_id: string | null;
  current_version: number;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateVersionRead {
  id: string;
  template_id: string;
  version: number;
  body_text: string;
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
  action:
    | 'submit'
    | 'approve'
    | 'reject'
    | 'request_changes'
    | 'publish'
    | 'archive';
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
  body_text: string;
  subject?: string | null;
  preview_text?: string | null;
}

export interface TemplateUpdatePayload {
  name?: string;
  category?: TemplateCategory;
  language?: string;
  body_text?: string;
  subject?: string | null;
  preview_text?: string | null;
  change_note?: string | null;
}

export interface TemplateListQuery {
  channel?: TemplateChannel;
  internal_status?: TemplateInternalStatus;
  external_status?: TemplateExternalStatus;
  q?: string;
  limit?: number;
  offset?: number;
}

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
      q: query.q,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<TemplateListResponse>(this.base, { params });
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

  versions(id: string): Observable<TemplateVersionRead[]> {
    return this.http.get<TemplateVersionRead[]>(`${this.base}/${id}/versions`);
  }

  getVersion(id: string, version: number): Observable<TemplateVersionRead> {
    return this.http.get<TemplateVersionRead>(
      `${this.base}/${id}/versions/${version}`,
    );
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

  requestChanges(
    id: string,
    payload: WorkflowActionPayload,
  ): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(
      `${this.base}/${id}/request-changes`,
      payload,
    );
  }

  publish(id: string, payload: WorkflowActionPayload = {}): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/publish`, payload);
  }

  archiveViaWorkflow(
    id: string,
    payload: WorkflowActionPayload = {},
  ): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(`${this.base}/${id}/archive`, payload);
  }

  // --- test send (Step 5) ----------------------------------------------

  testSend(id: string, payload: TestSendPayload): Observable<TemplateTestSendRead> {
    return this.http.post<TemplateTestSendRead>(
      `${this.base}/${id}/test-send`,
      payload,
    );
  }

  // --- external submission (Step 9) -----------------------------------

  submitExternal(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(
      `${this.base}/${id}/submit-external`,
      {},
    );
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

  /** Step 14 — manually re-query the provider for the live status.
   *  Counterpart of the hourly Celery sweep; the editor calls this
   *  when the operator clicks the "Refresh status" button. */
  syncExternal(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(
      `${this.base}/${id}/sync-external`,
      {},
    );
  }

  /** Step 14 — "Resubmit" affordance for templates Meta rejected.
   *  Backend resets `internal_status='draft'` + `external_status='n_a'`
   *  so the operator can edit the body and re-submit. */
  resubmit(id: string): Observable<TemplateRead> {
    return this.http.post<TemplateRead>(
      `${this.base}/${id}/resubmit`,
      {},
    );
  }

  // --- SMS DLT metadata (Step 12) -------------------------------------

  getSmsMetadata(id: string): Observable<SmsDltMetadata> {
    return this.http.get<SmsDltMetadata>(`${this.base}/${id}/sms-metadata`);
  }

  patchSmsMetadata(
    id: string,
    payload: SmsDltMetadataPatch,
  ): Observable<SmsDltMetadata> {
    return this.http.patch<SmsDltMetadata>(
      `${this.base}/${id}/sms-metadata`,
      payload,
    );
  }
}
