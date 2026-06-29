import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

/**
 * Automation engine API client.
 *
 * Wraps the Step-3 endpoints at `/api/v1/automations` (tasks/automation-engine).
 * Reads (`list / get / listRuns / listEventTypes`) are `automations.read`-
 * gated server-side; mutations (`create / patch / enable / disable /
 * delete`) need `automations.write`; run history needs the tighter
 * `automations.runs.read`. The page component renders mutation buttons
 * behind permission checks so the UI doesn't dangle un-clickable
 * affordances.
 */

export type TriggerChannel =
  | 'email'
  | 'whatsapp'
  | 'sms'
  | 'facebook'
  | 'instagram'
  | 'push'
  | 'web';

export type AutomationRunStatus =
  | 'queued'
  | 'dispatched'
  | 'sent'
  | 'failed'
  | 'skipped';

export interface TriggerRead {
  id: string;
  org_id: string;
  name: string;
  event_type: string;
  channel: TriggerChannel;
  template_id: string;
  enabled: boolean;
  conditions: Record<string, unknown>;
  delay_seconds: number;
  recipient_resolver: string;
  recipient_resolver_config: Record<string, unknown>;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunRead {
  id: string;
  org_id: string;
  trigger_id: string;
  event_id: string;
  event_payload: Record<string, unknown>;
  contact_id: string | null;
  user_id: string | null;
  status: AutomationRunStatus;
  channel_message_id: string | null;
  error: string | null;
  scheduled_at: string;
  dispatched_at: string | null;
  completed_at: string | null;
}

export interface TriggerListResponse {
  items: TriggerRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunListResponse {
  items: RunRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface TriggerCreatePayload {
  name: string;
  event_type: string;
  channel: TriggerChannel;
  template_id: string;
  enabled?: boolean;
  conditions?: Record<string, unknown>;
  delay_seconds?: number;
  recipient_resolver?: string;
  recipient_resolver_config?: Record<string, unknown>;
}

export interface TriggerUpdatePayload {
  name?: string;
  event_type?: string;
  channel?: TriggerChannel;
  template_id?: string;
  enabled?: boolean;
  conditions?: Record<string, unknown>;
  delay_seconds?: number;
  recipient_resolver?: string;
  recipient_resolver_config?: Record<string, unknown>;
}

export interface TriggerListQuery {
  event_type?: string;
  enabled?: boolean;
  channel?: TriggerChannel;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface RunListQuery {
  status?: AutomationRunStatus;
  since?: string;
  limit?: number;
  offset?: number;
}

export interface EventCatalogEntry {
  event_type: string;
  label: string;
  description: string;
  sample_payload: Record<string, unknown>;
}

export interface DryRunResult {
  would_match: boolean;
  skip_reason: string | null;
  would_send_to: string | null;
  rendered_subject: string | null;
  rendered_body: string | null;
}


@Injectable({ providedIn: 'root' })
export class AutomationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/automations`;

  list(query: TriggerListQuery = {}): Observable<TriggerListResponse> {
    const params = buildHttpParams({
      event_type: query.event_type,
      enabled: query.enabled,
      channel: query.channel,
      q: query.q,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<TriggerListResponse>(`${this.base}/triggers`, {
      params,
    });
  }

  get(id: string): Observable<TriggerRead> {
    return this.http.get<TriggerRead>(`${this.base}/triggers/${id}`);
  }

  create(payload: TriggerCreatePayload): Observable<TriggerRead> {
    return this.http.post<TriggerRead>(`${this.base}/triggers`, payload);
  }

  update(id: string, payload: TriggerUpdatePayload): Observable<TriggerRead> {
    return this.http.patch<TriggerRead>(
      `${this.base}/triggers/${id}`,
      payload,
    );
  }

  enable(id: string): Observable<TriggerRead> {
    return this.http.post<TriggerRead>(
      `${this.base}/triggers/${id}/enable`,
      {},
    );
  }

  disable(id: string): Observable<TriggerRead> {
    return this.http.post<TriggerRead>(
      `${this.base}/triggers/${id}/disable`,
      {},
    );
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/triggers/${id}`);
  }

  listRuns(triggerId: string, query: RunListQuery = {}): Observable<RunListResponse> {
    const params = buildHttpParams({
      status: query.status,
      since: query.since,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<RunListResponse>(
      `${this.base}/triggers/${triggerId}/runs`,
      { params },
    );
  }

  listEventTypes(): Observable<EventCatalogEntry[]> {
    return this.http.get<EventCatalogEntry[]>(`${this.base}/event-types`);
  }

  /** Step 8 — run the dispatcher path against a paste-in payload
   *  WITHOUT writing a run row or sending. Powers the editor's
   *  "Save & Test" modal. */
  dryRun(
    triggerId: string,
    payload: Record<string, unknown>,
  ): Observable<DryRunResult> {
    return this.http.post<DryRunResult>(
      `${this.base}/triggers/${triggerId}/dry-run`,
      { payload },
    );
  }
}
