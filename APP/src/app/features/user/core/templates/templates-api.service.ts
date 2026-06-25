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
  | 'web';

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
}
