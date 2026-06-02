import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

export type CallDirection = 'in' | 'out';

export interface Call {
  id: string;
  org_id: string;
  contact_id: string | null;
  direction: CallDirection;
  started_at: string;
  duration_sec: number;
  outcome_id: string | null;
  notes: string | null;
  recording_url: string | null;
  assigned_to_id: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
}

export interface CallListResponse {
  items: Call[];
  total: number;
  page: number;
  size: number;
}

export interface CallCreate {
  contact_id?: string | null;
  direction: CallDirection;
  started_at: string;
  duration_sec?: number;
  outcome_id?: string | null;
  notes?: string | null;
  recording_url?: string | null;
  assigned_to_id?: string | null;
  custom_data?: Record<string, unknown>;
}

export type CallUpdate = Partial<{
  contact_id: string | null;
  duration_sec: number;
  outcome_id: string | null;
  notes: string | null;
  recording_url: string | null;
  assigned_to_id: string | null;
  custom_data: Record<string, unknown>;
}>;

export interface CallOutcome {
  id: string;
  org_id: string;
  key: string;
  label: string;
  color: string;
  display_order: number;
  created_at: string;
}

export interface CallTranscript {
  id: string;
  org_id: string;
  call_id: string;
  text: string;
  language: string | null;
  created_at: string;
}

export interface CallTranscriptUpsert {
  text: string;
  language?: string | null;
}

export interface OutcomeDistributionRow {
  outcome_id: string | null;
  outcome_key: string | null;
  outcome_label: string | null;
  outcome_color: string | null;
  count: number;
}

export interface DailyVolumeRow {
  day: string;
  count: number;
}

export interface DirectionSplitRow {
  direction: CallDirection;
  count: number;
}

export interface CallAnalytics {
  from: string;
  to: string;
  outcomes: OutcomeDistributionRow[];
  daily: DailyVolumeRow[];
  direction: DirectionSplitRow[];
}

@Injectable({ providedIn: 'root' })
export class CallsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}`;

  // --- Calls ---

  listCalls(opts: {
    contact_id?: string;
    direction?: CallDirection;
    assigned_to?: string;
    page?: number;
    size?: number;
  } = {}): Observable<CallListResponse> {
    const params = buildHttpParams({
      contact_id: opts.contact_id,
      direction: opts.direction,
      assigned_to: opts.assigned_to,
      page: opts.page,
      size: opts.size,
    });
    return this.http.get<CallListResponse>(`${this.base}/calls`, { params });
  }

  getCall(id: string): Observable<Call> {
    return this.http.get<Call>(`${this.base}/calls/${id}`);
  }

  createCall(payload: CallCreate): Observable<Call> {
    return this.http.post<Call>(`${this.base}/calls`, payload);
  }

  updateCall(id: string, payload: CallUpdate): Observable<Call> {
    return this.http.patch<Call>(`${this.base}/calls/${id}`, payload);
  }

  deleteCall(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/calls/${id}`);
  }

  // --- Transcript ---

  getTranscript(callId: string): Observable<CallTranscript> {
    return this.http.get<CallTranscript>(
      `${this.base}/calls/${callId}/transcript`,
    );
  }

  upsertTranscript(
    callId: string,
    payload: CallTranscriptUpsert,
  ): Observable<CallTranscript> {
    return this.http.put<CallTranscript>(
      `${this.base}/calls/${callId}/transcript`,
      payload,
    );
  }

  // --- Outcomes ---

  listOutcomes(): Observable<CallOutcome[]> {
    return this.http.get<CallOutcome[]>(`${this.base}/call-outcomes`);
  }

  // --- Analytics ---

  analytics(from: string, to: string): Observable<CallAnalytics> {
    const params = buildHttpParams({ from, to });
    return this.http.get<CallAnalytics>(`${this.base}/calls/analytics`, {
      params,
    });
  }
}
