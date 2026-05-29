import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { ConversationChannel } from '../conversations/conversations-api.service';

export type CampaignStatus =
  | 'draft'
  | 'scheduled'
  | 'running'
  | 'done'
  | 'failed';

export type CampaignMessageStatus =
  | 'queued'
  | 'sent'
  | 'delivered'
  | 'read'
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
}

export type CampaignUpdate = Partial<{
  name: string;
  audience_filter: AudienceFilter;
  template: string | null;
  template_id: string | null;
  template_variables: Record<string, TemplateVariableBinding> | null;
  schedule_at: string | null;
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
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class CampaignsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/campaigns`;

  list(page = 1, size = 50): Observable<CampaignListResponse> {
    const params = new HttpParams().set('page', page).set('size', size);
    return this.http.get<CampaignListResponse>(this.base, { params });
  }

  get(id: string): Observable<Campaign> {
    return this.http.get<Campaign>(`${this.base}/${id}`);
  }

  create(payload: CampaignCreate): Observable<Campaign> {
    return this.http.post<Campaign>(this.base, payload);
  }

  update(id: string, payload: CampaignUpdate): Observable<Campaign> {
    return this.http.patch<Campaign>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  start(id: string): Observable<CampaignStartResponse> {
    return this.http.post<CampaignStartResponse>(
      `${this.base}/${id}/start`,
      {},
    );
  }

  stats(id: string): Observable<CampaignStats> {
    return this.http.get<CampaignStats>(`${this.base}/${id}/stats`);
  }

  listMessages(
    id: string,
    status?: CampaignMessageStatus,
  ): Observable<CampaignMessage[]> {
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    return this.http.get<CampaignMessage[]>(
      `${this.base}/${id}/messages`,
      { params },
    );
  }

  retry(campaignId: string, messageId: string): Observable<CampaignMessage> {
    return this.http.post<CampaignMessage>(
      `${this.base}/${campaignId}/messages/${messageId}/retry`,
      {},
    );
  }
}
