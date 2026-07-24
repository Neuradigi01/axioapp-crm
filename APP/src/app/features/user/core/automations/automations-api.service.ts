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

export type AutomationRunStatus = 'queued' | 'dispatched' | 'sent' | 'failed' | 'skipped';

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

/**
 * Filter-field metadata surfaced by the backend for the customer-
 * friendly condition builder (tasks/automation-conditions/ Step 1).
 * `enum_resolver` names a resolver key from step-2's registry —
 * `null` on non-enum types.
 */
export type FieldSpecType =
  | 'text'
  | 'number'
  | 'currency'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'enum';

export interface FieldSpec {
  path: string;
  label: string;
  type: FieldSpecType;
  group: string;
  enum_resolver: string | null;
  help_text: string | null;
}

export interface EventCatalogEntry {
  event_type: string;
  label: string;
  description: string;
  sample_payload: Record<string, unknown>;
  condition_fields: FieldSpec[];
}

/** One row in the value dropdown returned by step-2's live enum
 *  resolver endpoint. Matches `core.automation.enum_resolvers.EnumOption`. */
export interface EnumOption {
  value: string;
  label: string;
}

/** Response shape for step-5's matched-events preview
 *  (`POST /event-types/{event}/preview-matches`).
 *
 *  - `source: 'runs'` — scanned `tbl_automation_runs`; `matched` is
 *    exact unless `truncated`.
 *  - `source: 'none'` — no historical rows in the window; frontend
 *    renders the "no historical events available" hint instead of
 *    a misleading zero-count.
 *  - `truncated: true` — hit the 500-row cap; render "at least N".
 */
export interface PreviewMatchesResult {
  matched: number;
  scanned: number;
  window_days: number;
  source: 'runs' | 'none';
  truncated: boolean;
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
    return this.http.patch<TriggerRead>(`${this.base}/triggers/${id}`, payload);
  }

  enable(id: string): Observable<TriggerRead> {
    return this.http.post<TriggerRead>(`${this.base}/triggers/${id}/enable`, {});
  }

  disable(id: string): Observable<TriggerRead> {
    return this.http.post<TriggerRead>(`${this.base}/triggers/${id}/disable`, {});
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
    return this.http.get<RunListResponse>(`${this.base}/triggers/${triggerId}/runs`, { params });
  }

  listEventTypes(): Observable<EventCatalogEntry[]> {
    return this.http.get<EventCatalogEntry[]>(`${this.base}/event-types`);
  }

  /** tasks/automation-conditions/ Step 2 — fetch the caller org's
   *  live options for one enum-typed field on one event. Powers the
   *  condition-builder's Value dropdown for pipeline stages / lead
   *  sources / users / etc. Errors:
   *    - 404 `automation.event_not_found` — event isn't in the catalog.
   *    - 404 `automation.field_not_found` — field isn't in the event's `condition_fields`.
   *    - 422 `automation.field_not_enum`  — field's type isn't `enum`.
   *  Zero-rows is NOT an error — the frontend renders a "no options" hint. */
  listFieldValues(eventType: string, field: string): Observable<EnumOption[]> {
    return this.http.post<EnumOption[]>(
      `${this.base}/event-types/${encodeURIComponent(eventType)}/field-values`,
      { field },
    );
  }

  /** tasks/automation-conditions/ Step 5 — count how many
   *  historical events in the last `windowDays` would match the
   *  customer's draft condition. Informational only; no dispatch,
   *  no side effects. Fires from the condition builder on a
   *  debounced AST change. */
  previewMatches(
    eventType: string,
    conditions: Record<string, unknown>,
    windowDays: number = 7,
  ): Observable<PreviewMatchesResult> {
    return this.http.post<PreviewMatchesResult>(
      `${this.base}/event-types/${encodeURIComponent(eventType)}/preview-matches`,
      { conditions, window_days: windowDays },
    );
  }

  /** Step 8 — run the dispatcher path against a paste-in payload
   *  WITHOUT writing a run row or sending. Powers the editor's
   *  "Save & Test" modal. */
  dryRun(triggerId: string, payload: Record<string, unknown>): Observable<DryRunResult> {
    return this.http.post<DryRunResult>(`${this.base}/triggers/${triggerId}/dry-run`, { payload });
  }

  /** Step 9 — re-queue a failed run. Refuses non-failed states
   *  server-side with 409 + a structured error code. */
  retry(runId: string): Observable<RunRead> {
    return this.http.post<RunRead>(`${this.base}/runs/${runId}/retry`, {});
  }

  /** Step 9 — manually fire a saved trigger with the supplied
   *  payload. Writes a fresh run row with a synthetic
   *  `event_id='manual:...'`. */
  runNow(triggerId: string, payload: Record<string, unknown>): Observable<RunRead> {
    return this.http.post<RunRead>(`${this.base}/triggers/${triggerId}/run-now`, { payload });
  }

  /** Step 9 — general run-history filter; the contact detail
   *  Automations tab passes ``contact_id``. */
  listRunsByFilters(query: {
    contact_id?: string;
    trigger_id?: string;
    status?: AutomationRunStatus;
    since?: string;
    limit?: number;
    offset?: number;
  }): Observable<RunListResponse> {
    const params = buildHttpParams({
      contact_id: query.contact_id,
      trigger_id: query.trigger_id,
      status: query.status,
      since: query.since,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<RunListResponse>(`${this.base}/runs`, { params });
  }
}
