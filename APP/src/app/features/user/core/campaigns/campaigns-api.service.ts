import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { ConversationChannel } from '../conversations/conversations-api.service';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams } from '../shared/services/query-builder';

export type CampaignStatus = 'draft' | 'scheduled' | 'running' | 'done' | 'failed';

export type CampaignMessageStatus =
  | 'queued'
  | 'sent'
  | 'delivered'
  | 'read'
  | 'opened'
  | 'clicked'
  | 'failed';

export interface AudienceFilter {
  q?: string;
  source?: string;
  tag?: string;
  /** Saved contact group id. Mutually exclusive with q/source/tag —
   *  backend rejects mixed payloads with 422. */
  group_id?: string;
}

/** One `{{n}}` binding in `template_variables`. `kind=static` is
 *  literal text every recipient sees; `kind=field` resolves against
 *  the contact at dispatch time (Step 3.5.6). */
export interface TemplateVariableBinding {
  kind: 'static' | 'field';
  value: string;
}

export interface Campaign {
  id: string;
  org_id: string;
  name: string;
  channel: ConversationChannel;
  audience_filter: AudienceFilter;
  template: string | null;
  template_id: string | null;
  template_variables: Record<string, TemplateVariableBinding> | null;
  schedule_at: string | null;
  /** Campaigns v1 Step 03 — Email sender identity + subject + preheader.
   *  NULL for non-Email campaigns. Required-when-Email is enforced by
   *  the backend `_email_channel_requires_sender_and_subject` model
   *  validator; the frontend mirrors the same requirement via the
   *  create modal's disabled-submit gate. */
  email_account_id: string | null;
  sender_name: string | null;
  reply_to: string | null;
  subject: string | null;
  preheader: string | null;
  /** Campaigns v1 Step 04 — inline HTML body for Email campaigns
   *  that don't reference a template. Null for template-backed and
   *  non-Email campaigns. Sanitised server-side on every write. */
  body_html: string | null;
  status: CampaignStatus;
  created_by_id: string | null;
  created_at: string;
}

export interface CampaignListResponse {
  items: Campaign[];
  total: number;
  page: number;
  size: number;
}

export interface CampaignCreate {
  name: string;
  channel: ConversationChannel;
  audience_filter?: AudienceFilter;
  template?: string | null;
  template_id?: string | null;
  template_variables?: Record<string, TemplateVariableBinding> | null;
  schedule_at?: string | null;
  /** Step 27b — multi-number Send-From. NULL keeps the existing
   *  "use org default" behaviour; a string pins the dispatcher to
   *  the matching Meta phone-number-id. */
  send_from_phone_id?: string | null;
  /** Step 29 — A/B test config. When `is_ab_test` is true, both
   *  variant_*_template_id fields and `winner_metric` are required;
   *  the single-template `template` / `template_id` fields are
   *  ignored. Audience size ≥ 50 enforced server-side on start. */
  is_ab_test?: boolean;
  variant_a_template_id?: string | null;
  variant_b_template_id?: string | null;
  split_ratio?: number;
  winner_metric?: 'reply_rate' | 'read_rate' | 'click_rate' | null;
  winner_holdback_hours?: number;
  /** Campaigns v1 Step 03 — Email sender identity + subject + preheader.
   *  Required when `channel === 'email'`; ignored for every other
   *  channel. Backend rejects with 422 if any required field is
   *  missing on an Email payload. */
  email_account_id?: string | null;
  sender_name?: string | null;
  reply_to?: string | null;
  subject?: string | null;
  preheader?: string | null;
  /** Campaigns v1 Step 04 — inline HTML body for Email campaigns
   *  that don't reference a template. Mutually exclusive with
   *  `template` / `template_id`; backend enforces the exactly-one
   *  invariant. */
  body_html?: string | null;
}

export type CampaignUpdate = Partial<{
  name: string;
  audience_filter: AudienceFilter;
  template: string | null;
  template_id: string | null;
  template_variables: Record<string, TemplateVariableBinding> | null;
  schedule_at: string | null;
  /** Campaigns v1 Step 03 — Email fields editable on Draft campaigns.
   *  Channel itself stays immutable post-create. */
  email_account_id: string | null;
  sender_name: string | null;
  reply_to: string | null;
  subject: string | null;
  preheader: string | null;
  /** Campaigns v1 Step 04 — inline HTML body edit for Email drafts. */
  body_html: string | null;
}>;

export interface CampaignStartResponse {
  campaign_id: string;
  status: CampaignStatus;
  audience_size: number;
  chunks_enqueued: number;
  scheduled_at: string | null;
}

export interface CampaignStats {
  campaign_id: string;
  status: CampaignStatus;
  audience_size: number;
  queued: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  /** Campaigns v1 Step 05 — Email tracking counters. Always present
   *  on the response (0 for WA campaigns) so the frontend can render
   *  the Email funnel without a second endpoint. */
  opened: number;
  clicked: number;
  bounced: number;
  unsubscribed: number;
}

export interface CampaignMessage {
  id: string;
  org_id: string;
  campaign_id: string;
  contact_id: string;
  channel_message_id: string | null;
  status: CampaignMessageStatus;
  error: string | null;
  sent_at: string | null;
  /** Step 3.5.12 — stamped when Meta reports `status='delivered'`. */
  delivered_at: string | null;
  /** Step 3.5.12 — stamped when Meta reports `status='read'`. */
  read_at: string | null;
  /** Campaigns v1 Step 05 — Email tracking timestamps. `opened_at`
   *  fires on the first pixel hit; `first_click_at` on the first
   *  tracked link click; `bounced_at` when the bounce classifier
   *  flips the row failed. `unsubscribed_at` lands in Step 06. */
  opened_at: string | null;
  first_click_at: string | null;
  bounced_at: string | null;
  bounce_type: string | null;
  unsubscribed_at: string | null;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class CampaignsApiService extends BaseCrudApiService<
  Campaign,
  CampaignCreate,
  CampaignUpdate
> {
  protected readonly base = `${environment.apiBaseUrl}/campaigns`;

  list(page = 1, size = 50): Observable<CampaignListResponse> {
    const params = buildHttpParams({ page, size });
    return this.http.get<CampaignListResponse>(this.base, { params });
  }

  start(id: string): Observable<CampaignStartResponse> {
    return this.http.post<CampaignStartResponse>(`${this.base}/${id}/start`, {});
  }

  stats(id: string): Observable<CampaignStats> {
    return this.http.get<CampaignStats>(`${this.base}/${id}/stats`);
  }

  listMessages(id: string, status?: CampaignMessageStatus): Observable<CampaignMessage[]> {
    const params = buildHttpParams({ status });
    return this.http.get<CampaignMessage[]>(`${this.base}/${id}/messages`, { params });
  }

  retry(campaignId: string, messageId: string): Observable<CampaignMessage> {
    return this.http.post<CampaignMessage>(
      `${this.base}/${campaignId}/messages/${messageId}/retry`,
      {},
    );
  }
}
