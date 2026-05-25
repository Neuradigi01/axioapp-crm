import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/**
 * Typed Angular wrapper for the admin embed-widget endpoints
 * (Steps 1–3 of the embeddable-widget track).
 *
 * Public endpoints (`/embed/leads`, `/embed/config/public`) are NOT
 * consumed by the in-app Settings UI — they're for the standalone
 * widget JS bundle on customer websites. So this service deliberately
 * only wraps the admin (JWT-gated) endpoints.
 */

export type WidgetFieldKey =
  | 'full_name'
  | 'phone'
  | 'email'
  | 'interest'
  | 'notes';

export type WidgetFieldType = 'text' | 'email' | 'tel' | 'textarea' | 'select';

export interface WidgetConfigField {
  key: WidgetFieldKey;
  label: string;
  placeholder?: string | null;
  required: boolean;
  order: number;
  field_type: WidgetFieldType;
  options?: string[] | null;
}

export interface WidgetConfigBranding {
  logo_url?: string | null;
  accent_color: string;
  show_powered_by: boolean;
}

/**
 * Admin projection of the org's spam-protection settings. The
 * `recaptcha_secret_key` round-trips through the admin endpoints
 * (Owner can edit it) but never reaches the public widget bundle
 * — the backend strips it before responding to `/embed/config/public`.
 */
export interface WidgetConfigSpamProtection {
  recaptcha_enabled: boolean;
  recaptcha_site_key: string | null;
  recaptcha_secret_key: string | null;
  min_fill_time_ms: number;
}

export interface WidgetConfigDocument {
  fields: WidgetConfigField[];
  submit_button_label: string;
  thank_you_message: string;
  thank_you_url?: string | null;
  branding: WidgetConfigBranding;
  spam_protection: WidgetConfigSpamProtection;
}

export interface WidgetConfigRead {
  id: string;
  org_id: string;
  config: WidgetConfigDocument;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WidgetConfigUpdatePayload {
  fields?: WidgetConfigField[];
  submit_button_label?: string;
  thank_you_message?: string;
  thank_you_url?: string | null;
  branding?: WidgetConfigBranding;
  spam_protection?: WidgetConfigSpamProtection;
}

export interface EmbedKey {
  id: string;
  org_id: string;
  name: string | null;
  prefix: string;
  created_by: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  created_at: string;
}

export interface EmbedKeyIssueResponse {
  id: string;
  name: string | null;
  prefix: string;
  /** Plaintext — appears in this response ONCE; never retrievable again. */
  secret: string;
  created_at: string;
}


@Injectable({ providedIn: 'root' })
export class EmbedApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/embed`;

  listKeys(): Observable<EmbedKey[]> {
    return this.http.get<EmbedKey[]>(`${this.base}/keys`);
  }

  issueKey(name: string | null): Observable<EmbedKeyIssueResponse> {
    return this.http.post<EmbedKeyIssueResponse>(`${this.base}/keys`, {
      name: name || null,
    });
  }

  revokeKey(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/keys/${id}`);
  }

  getConfig(): Observable<WidgetConfigRead> {
    return this.http.get<WidgetConfigRead>(`${this.base}/config`);
  }

  updateConfig(
    payload: WidgetConfigUpdatePayload,
  ): Observable<WidgetConfigRead> {
    return this.http.put<WidgetConfigRead>(`${this.base}/config`, payload);
  }

  // --- Submission log (Step 9) ---------------------------------------

  listSubmissions(
    filters: EmbedSubmissionListFilters,
  ): Observable<EmbedSubmissionListResponse> {
    let params = new HttpParams()
      .set('page', String(filters.page ?? 1))
      .set('page_size', String(filters.page_size ?? 25));
    if (filters.outcome) params = params.set('outcome', filters.outcome);
    if (filters.from) params = params.set('from', filters.from);
    if (filters.to) params = params.set('to', filters.to);
    return this.http.get<EmbedSubmissionListResponse>(
      `${this.base}/submissions`,
      { params },
    );
  }

  getSubmissionSummary(
    range: EmbedSubmissionRange,
  ): Observable<EmbedSubmissionSummary> {
    let params = new HttpParams();
    if (range.from) params = params.set('from', range.from);
    if (range.to) params = params.set('to', range.to);
    return this.http.get<EmbedSubmissionSummary>(
      `${this.base}/submissions/summary`,
      { params },
    );
  }
}


// --- Submission log shapes (Step 9) ------------------------------------

export type EmbedSubmissionOutcome =
  | 'accepted'
  | 'rejected_spam'
  | 'rate_limited'
  | 'invalid_payload';

export interface EmbedSubmissionRead {
  id: string;
  key_id: string | null;
  lead_id: string | null;
  outcome: EmbedSubmissionOutcome;
  reason: string | null;
  ip_hash: string | null;
  referrer: string | null;
  landing_url: string | null;
  created_at: string;
}

export interface EmbedSubmissionListResponse {
  items: EmbedSubmissionRead[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmbedSubmissionListFilters {
  outcome?: EmbedSubmissionOutcome | null;
  from?: string | null;
  to?: string | null;
  page?: number;
  page_size?: number;
}

export interface EmbedSubmissionRange {
  from?: string | null;
  to?: string | null;
}

export interface EmbedSubmissionDayBucket {
  day: string;
  accepted: number;
  rejected_spam: number;
  rate_limited: number;
  invalid_payload: number;
}

export interface EmbedSubmissionSummary {
  range_from: string;
  range_to: string;
  by_outcome: Record<EmbedSubmissionOutcome, number>;
  by_day: EmbedSubmissionDayBucket[];
}
