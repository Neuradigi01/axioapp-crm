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
  /** Restrict to contacts with at least one Lead whose ``status`` /
   *  pipeline-stage / ``source`` sits in the given set. Each field is
   *  OR-within, AND-across — mirrors the ``/contacts?lead_*=…`` list
   *  query. Applied at dispatch time so filter mode stays dynamic. */
  lead_status?: string[];
  lead_stage?: string[];
  lead_source?: string[];
  /** Multi-form Step 7 — narrow "Forms" leads to specific form ids.
   *  Applied at dispatch time via an EXISTS subquery on
   *  ``tbl_leads.attribution->>'form_id'``. */
  lead_form_id?: string[];
  /** Saved contact group id. Mutually exclusive with the filter fields
   *  above — backend rejects mixed payloads with 422. */
  group_id?: string;
  /** Explicit hand-picked contact ids. Mutually exclusive with all
   *  other modes — set from the campaign modal's live preview when
   *  the operator ticks specific rows. Frozen at save time. */
  contact_ids?: string[];
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
  /** Migration 0213 — alternate SMTP sender identity. Exactly one of
   *  `email_account_id` / `smtp_sender_id` is populated on Email rows;
   *  both are `null` on non-Email campaigns. */
  smtp_sender_id: string | null;
  sender_name: string | null;
  reply_to: string | null;
  subject: string | null;
  preheader: string | null;
  /** Campaigns v1 Step 04 — inline HTML body for Email campaigns
   *  that don't reference a template. Null for template-backed and
   *  non-Email campaigns. Sanitised server-side on every write. */
  body_html: string | null;
  status: CampaignStatus;
  /** Migration 0238 — soft-archive timestamp. Non-null hides the
   *  campaign from the default list + sender-in-use pre-check but
   *  preserves the per-message metrics rows. */
  archived_at: string | null;
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
  /** Migration 0213 — alternate SMTP sender identity. Send exactly
   *  one of `email_account_id` (OAuth mailbox) or `smtp_sender_id`
   *  (verified SMTP identity) for Email campaigns. Backend rejects
   *  with 422 if both / neither / non-Email carries either. */
  smtp_sender_id?: string | null;
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
  /** Migration 0213 — swap a draft Email campaign between an OAuth
   *  mailbox and a verified SMTP sender identity. */
  smtp_sender_id: string | null;
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

/** One blocker / warning surfaced by the readiness pre-flight. */
export interface CampaignReadinessItem {
  code: string;
  message: string;
}

/** Campaigns v1 Step 07c — structured pre-flight for the Start button.
 *  Blockers = the same set of errors ``POST /start`` would 400 with;
 *  warnings = soft degradations (unverified DKIM etc.) the operator
 *  can still Start through. */
export interface CampaignReadiness {
  campaign_id: string;
  channel: string;
  audience_size: number;
  eligible_count: number;
  excluded_opted_out: number;
  excluded_no_email: number;
  excluded_bounced: number;
  blockers: CampaignReadinessItem[];
  warnings: CampaignReadinessItem[];
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

export interface CampaignDashboardStats {
  /** Start of the aggregation window (first of the current month, UTC). */
  since: string;
  sent: number;
  delivered: number;
  read: number;
  /** `delivered / sent`. `null` when `sent` is 0 so the UI can render
   *  "—" instead of a misleading 0%. */
  delivery_rate: number | null;
  /** `read / delivered`. `null` when `delivered` is 0. */
  read_rate: number | null;
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

  list(
    page = 1,
    size = 50,
    opts: { include_archived?: boolean; archived_only?: boolean } = {},
  ): Observable<CampaignListResponse> {
    const params = buildHttpParams({
      page,
      size,
      include_archived: opts.include_archived,
      archived_only: opts.archived_only,
    });
    return this.http.get<CampaignListResponse>(this.base, { params });
  }

  archive(id: string): Observable<Campaign> {
    return this.http.post<Campaign>(`${this.base}/${id}/archive`, {});
  }

  unarchive(id: string): Observable<Campaign> {
    return this.http.post<Campaign>(`${this.base}/${id}/unarchive`, {});
  }

  start(id: string): Observable<CampaignStartResponse> {
    return this.http.post<CampaignStartResponse>(`${this.base}/${id}/start`, {});
  }

  readiness(id: string): Observable<CampaignReadiness> {
    return this.http.get<CampaignReadiness>(`${this.base}/${id}/readiness`);
  }

  stats(id: string): Observable<CampaignStats> {
    return this.http.get<CampaignStats>(`${this.base}/${id}/stats`);
  }

  dashboardStats(): Observable<CampaignDashboardStats> {
    return this.http.get<CampaignDashboardStats>(`${this.base}/dashboard-stats`);
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
