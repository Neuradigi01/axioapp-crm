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
  /** True when a file has been uploaded via `POST /calls/{id}/recording`.
   *  Playback URL is derived via `recordingStreamUrl(id)`. */
  has_recording: boolean;
  assigned_to_id: string | null;
  /** User who logged the call. Stamped server-side from the JWT on
   *  create; null for historical rows written before this field existed. */
  created_by_id: string | null;
  /** Denormalised display name for the linked contact — populated by
   *  the list endpoint via a bulk lookup so the table renders without
   *  N+1 fetches. Null for single-row reads (GET, POST). */
  contact_name: string | null;
  /** Denormalised display name for `created_by_id`. Same shape as
   *  `contact_name`. Falls back to null when the user row is gone. */
  created_by_name: string | null;
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

export interface CallOutcomeCreate {
  key: string;
  label: string;
  color: string;
  display_order: number;
}

export type CallOutcomeUpdate = Partial<Pick<CallOutcome, 'label' | 'color' | 'display_order'>>;

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

  listCalls(
    opts: {
      contact_id?: string;
      direction?: CallDirection;
      assigned_to?: string;
      page?: number;
      size?: number;
    } = {},
  ): Observable<CallListResponse> {
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

  // --- Recording upload / playback ---

  /** Upload a recording file (mp3/m4a/ogg/wav, max 30 MB) as
   *  multipart/form-data. Returns the updated Call so the caller can
   *  swap in the fresh `has_recording=true` flag optimistically. */
  uploadRecording(id: string, file: File): Observable<Call> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<Call>(`${this.base}/calls/${id}/recording`, form);
  }

  /** Absolute URL the streaming endpoint lives at. Rarely used directly
   *  — `<audio src>` can't send the JWT header, so most callers should
   *  use `fetchRecording()` instead and wrap the bytes in a blob URL. */
  recordingStreamUrl(id: string): string {
    return `${this.base}/calls/${id}/recording`;
  }

  /** Fetch the recording as a Blob (JWT auto-sent by the interceptor).
   *  The caller wraps the blob in `URL.createObjectURL` and feeds it to
   *  the `<audio>` element. 404s when no upload exists. */
  fetchRecording(id: string): Observable<Blob> {
    return this.http.get(`${this.base}/calls/${id}/recording`, {
      responseType: 'blob',
    });
  }

  // --- Transcript ---

  getTranscript(callId: string): Observable<CallTranscript> {
    return this.http.get<CallTranscript>(`${this.base}/calls/${callId}/transcript`);
  }

  upsertTranscript(callId: string, payload: CallTranscriptUpsert): Observable<CallTranscript> {
    return this.http.put<CallTranscript>(`${this.base}/calls/${callId}/transcript`, payload);
  }

  // --- Outcomes ---

  listOutcomes(): Observable<CallOutcome[]> {
    return this.http.get<CallOutcome[]>(`${this.base}/call-outcomes`);
  }

  createOutcome(payload: CallOutcomeCreate): Observable<CallOutcome> {
    return this.http.post<CallOutcome>(`${this.base}/call-outcomes`, payload);
  }

  updateOutcome(id: string, payload: CallOutcomeUpdate): Observable<CallOutcome> {
    return this.http.patch<CallOutcome>(`${this.base}/call-outcomes/${id}`, payload);
  }

  deleteOutcome(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/call-outcomes/${id}`);
  }

  // --- Analytics ---

  analytics(from: string, to: string): Observable<CallAnalytics> {
    const params = buildHttpParams({ from, to });
    return this.http.get<CallAnalytics>(`${this.base}/calls/analytics`, {
      params,
    });
  }
}
