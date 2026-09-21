/**
 * Quarantine + Filter-Rules API service (tasks/email-quarantine-filters Step 5).
 *
 * Wraps two endpoint families:
 *
 *   Filter rules:
 *     * ``GET    /email-filter-rules``
 *     * ``POST   /email-filter-rules``
 *     * ``DELETE /email-filter-rules/{id}``
 *
 *   Quarantine:
 *     * ``GET   /email-quarantine``
 *     * ``POST  /email-quarantine/{id}/release``
 *     * ``POST  /email-quarantine/{id}/discard``
 *     * ``POST  /email-quarantine/bulk-release``
 *
 * All Owner/Admin — gated by ``email.accounts.manage`` server-side.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type RuleType = 'allow' | 'block';
export type MatchKind = 'email_address' | 'email_domain' | 'contact_flag';
export type ReasonCode =
  | 'size_exceeded'
  | 'blocked_sender'
  | 'rate_capped'
  | 'spam_verdict'
  | 'virus_verdict';
export type QuarantineStatus = 'held' | 'released' | 'discarded' | 'auto_purged';

export interface FilterRule {
  id: string;
  org_id: string;
  endpoint_id: string | null;
  rule_type: RuleType;
  match_kind: MatchKind;
  match_value: string;
  label: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateFilterRuleRequest {
  rule_type: RuleType;
  match_kind: MatchKind;
  match_value: string;
  label?: string | null;
  endpoint_id?: string | null;
}

export interface QuarantineRow {
  id: string;
  org_id: string;
  endpoint_id: string | null;
  mailgun_delivery_id: string | null;
  from_address: string;
  from_display_name: string | null;
  to_recipient: string;
  subject: string | null;
  body_snippet: string | null;
  attachment_summary: Array<Record<string, unknown>>;
  reason_code: ReasonCode;
  reason_detail: Record<string, unknown>;
  status: QuarantineStatus;
  blocked_release: boolean;
  held_at: string;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
}

export interface QuarantineListResponse {
  items: QuarantineRow[];
  total: number;
}

export interface BulkReleaseResponse {
  released: string[];
  rejected: Array<{ id: string; reason: string }>;
}

export interface QuarantineListParams {
  status?: QuarantineStatus;
  reason_code?: ReasonCode;
  limit?: number;
  offset?: number;
}

@Injectable({ providedIn: 'root' })
export class QuarantineService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // ── Filter rules ──────────────────────────────────────────────
  listRules(endpointId?: string): Observable<FilterRule[]> {
    let params = new HttpParams();
    if (endpointId) params = params.set('endpoint_id', endpointId);
    return this.http.get<FilterRule[]>(`${this.base}/email-filter-rules`, {
      params,
    });
  }

  createRule(payload: CreateFilterRuleRequest): Observable<FilterRule> {
    return this.http.post<FilterRule>(`${this.base}/email-filter-rules`, payload);
  }

  deleteRule(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/email-filter-rules/${id}`);
  }

  // ── Quarantine ────────────────────────────────────────────────
  listQuarantine(params: QuarantineListParams = {}): Observable<QuarantineListResponse> {
    let httpParams = new HttpParams();
    if (params.status) httpParams = httpParams.set('status', params.status);
    if (params.reason_code) httpParams = httpParams.set('reason_code', params.reason_code);
    if (params.limit != null) httpParams = httpParams.set('limit', String(params.limit));
    if (params.offset != null) httpParams = httpParams.set('offset', String(params.offset));
    return this.http.get<QuarantineListResponse>(`${this.base}/email-quarantine`, {
      params: httpParams,
    });
  }

  release(id: string): Observable<QuarantineRow> {
    return this.http.post<QuarantineRow>(`${this.base}/email-quarantine/${id}/release`, {});
  }

  discard(id: string): Observable<void> {
    return this.http.post<void>(`${this.base}/email-quarantine/${id}/discard`, {});
  }

  bulkRelease(ids: string[]): Observable<BulkReleaseResponse> {
    return this.http.post<BulkReleaseResponse>(`${this.base}/email-quarantine/bulk-release`, {
      ids,
    });
  }
}
