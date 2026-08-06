import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

/**
 * Workflows API client.
 *
 * Wraps the Step-3 endpoints at `/api/v1/workflows` (tasks/workflows).
 * Reads are gated server-side on `workflows.read`; mutations need
 * `workflows.write`; activate / pause need `workflows.activate`;
 * clone needs `workflows.clone`. The page renders mutation buttons
 * behind permission checks so the UI doesn't dangle un-clickable
 * affordances.
 */

export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived';
export type WorkflowReEnrollment = 'once' | 'daily' | 'never';
export type WorkflowRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'paused'
  | 'canceled'
  | 'errored';
export type WorkflowRunOutcome = 'goal_reached' | 'completed' | 'canceled' | 'errored' | null;
export type WorkflowStepRunStatus = 'pending' | 'running' | 'completed' | 'skipped' | 'errored';

/** Loose graph type at Step 13 — Step 14 + 15 tighten to typed node shapes
 *  when the canvas + node editor ship. */
export interface WorkflowGraph {
  nodes: Array<{
    id: string;
    type: string;
    position?: { x: number; y: number };
    config?: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    label?: string | null;
  }>;
}

export interface WorkflowRead {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  category: string;
  folder_id: string | null;
  status: WorkflowStatus;
  current_version: number;
  re_enrollment_rule: WorkflowReEnrollment;
  is_marketing: boolean;
  graph: WorkflowGraph;
  goal_node_id: string | null;
  cost_per_run_cents: number;
  enabled_event_types: string[];
  ab_sibling_id: string | null;
  // Step 18 — A/B columns surfaced for the canvas banner +
  // comparison page. Null when the workflow isn't part of an A/B
  // test.
  ab_paired_workflow_id?: string | null;
  ab_test_started_at?: string | null;
  ab_test_holdback_until?: string | null;
  ab_test_winner_metric?: 'goal_conversion' | 'reply_rate' | 'open_rate' | 'custom' | null;
  ab_test_min_runs_per_variant?: number | null;
  ab_test_winner_workflow_id?: string | null;
  ab_test_decided_at?: string | null;
  // Step 21 — system-default workflows install active + are protected
  // from archive. List page renders a "System" badge + hides the
  // archive affordance on these rows.
  is_system_default?: boolean;
  created_at: string;
  updated_at: string;
  // tasks/workflow-scheduling Step 5 — populated by the list endpoint
  // via the schedule-summary aggregate join. Optional so single-workflow
  // GET (which doesn't compute the aggregate) can omit them.
  active_schedule_count?: number;
  next_scheduled_at?: string | null;
}

/** Per-row summary the list page renders. Identical shape to
 *  `WorkflowRead` at Step 13 — Step 19 will widen this with
 *  cached running-count + completed-this-week counters. */
export type WorkflowSummary = WorkflowRead;

export interface WorkflowListResponse {
  items: WorkflowRead[];
  total: number;
}

export interface WorkflowListQuery {
  status?: WorkflowStatus;
  category?: string;
  folder_id?: string;
  q?: string;
  /** Filter to workflows with (true) or without (false) an active
   *  schedule. Omitted = no filter. */
  has_schedule?: boolean;
  limit?: number;
  offset?: number;
}

export interface WorkflowCreatePayload {
  name: string;
  description?: string | null;
  category?: string;
  folder_id?: string | null;
  is_marketing?: boolean;
  re_enrollment_rule?: WorkflowReEnrollment;
  graph?: WorkflowGraph;
  goal_node_id?: string | null;
  cost_per_run_cents?: number;
}

export interface WorkflowUpdatePayload {
  name?: string;
  description?: string | null;
  category?: string;
  folder_id?: string | null;
  status?: WorkflowStatus;
  is_marketing?: boolean;
  re_enrollment_rule?: WorkflowReEnrollment;
  graph?: WorkflowGraph;
  goal_node_id?: string | null;
  cost_per_run_cents?: number;
  /** Step 17 — describes the change saved with this PATCH. Lands on
   *  the new `tbl_workflow_versions` row + drives the version-history
   *  drawer's column. */
  change_note?: string | null;
}

export interface WorkflowFolder {
  id: string;
  org_id: string;
  name: string;
  parent_folder_id: string | null;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface WorkflowFolderCreatePayload {
  name: string;
  parent_folder_id?: string | null;
  display_order?: number;
}

export interface WorkflowFolderUpdatePayload {
  name?: string;
  parent_folder_id?: string | null;
  display_order?: number;
}

export interface WorkflowRunRead {
  id: string;
  workflow_id: string;
  version: number;
  contact_id: string | null;
  trigger_event_id: string | null;
  status: WorkflowRunStatus;
  current_node_id: string | null;
  outcome: WorkflowRunOutcome;
  error: string | null;
  started_at: string;
  next_step_at: string | null;
  completed_at: string | null;
}

export interface WorkflowStepRunRead {
  id: string;
  run_id: string;
  node_id: string;
  step_index: number;
  status: WorkflowStepRunStatus;
  started_at: string;
  completed_at: string | null;
  output_edge_label: string | null;
  skip_reason: string | null;
  payload: Record<string, unknown>;
  error: string | null;
}

export interface WorkflowRunListResponse {
  items: WorkflowRunRead[];
  total: number;
}

export interface WorkflowRunListQuery {
  status?: WorkflowRunStatus;
  contact_id?: string;
  limit?: number;
  offset?: number;
}

export interface WorkflowTestFireRequest {
  event_type?: string;
  contact_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface WorkflowTestFireStep {
  node_id: string;
  node_type: string;
  edge_label: string | null;
  skip_reason: string | null;
}

export interface WorkflowTestFireResponse {
  workflow_id: string;
  steps: WorkflowTestFireStep[];
  outcome: 'goal_reached' | 'completed' | 'canceled' | 'errored';
  error: string | null;
}

export interface WorkflowGalleryEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  channels: string[];
  goal_node_label: string;
  est_setup_time_minutes: number;
  est_completion_rate_pct: number;
  screenshot_url: string | null;
  graph_preview: WorkflowGraph;
  is_marketing: boolean;
  re_enrollment_rule: WorkflowReEnrollment;
}

export interface WorkflowGalleryListResponse {
  items: WorkflowGalleryEntry[];
  total: number;
}

export interface WorkflowGalleryCloneRequest {
  name?: string | null;
  folder_id?: string | null;
}

// --- Step 17: version history + rollback + import / export -------------

export interface WorkflowVersionSummary {
  id: string;
  version: number;
  change_note: string | null;
  created_by_user_id: string | null;
  created_at: string;
}

export interface WorkflowVersionListResponse {
  items: WorkflowVersionSummary[];
  total: number;
}

export interface WorkflowVersionDetail extends WorkflowVersionSummary {
  workflow_id: string;
  graph: WorkflowGraph;
}

export interface WorkflowRollbackRequest {
  target_version: number;
  change_note?: string | null;
}

export interface WorkflowExportBody {
  name: string;
  description: string | null;
  category: string;
  graph: WorkflowGraph;
  re_enrollment_rule: WorkflowReEnrollment;
  is_marketing: boolean;
  goal_node_id: string | null;
  cost_per_run_cents: number;
  schema_version: number;
}

export interface WorkflowImportRequest {
  json: WorkflowExportBody;
  target_folder_id?: string | null;
  name?: string | null;
}

// --- Step 19: analytics + diagnostics + run-detail ---------------------

export interface WorkflowAnalyticsTotals {
  enrolled: number;
  completed: number;
  goal_reached: number;
  errored: number;
  running: number;
  conversion_rate: number;
  avg_completion_seconds: number | null;
  estimated_cost_cents: number;
}

export interface WorkflowFunnelRow {
  node_id: string;
  label: string;
  node_type: string;
  total: number;
  completed_count: number;
  skipped_count: number;
  errored_count: number;
}

export interface WorkflowSendMetricRow {
  channel: string;
  total: number;
  delivered: number;
  skipped: number;
  errored: number;
  delivery_rate: number;
}

export interface WorkflowAnalyticsResponse {
  workflow_id: string;
  window: { since: string; until: string };
  totals: WorkflowAnalyticsTotals;
  funnel: WorkflowFunnelRow[];
  skip_reasons: Record<string, Record<string, number>>;
  send_metrics: WorkflowSendMetricRow[];
}

export interface WorkflowDailyRateRow {
  date: string;
  enrolled: number;
  completed: number;
  goal_reached: number;
}

export interface WorkflowDailyRateResponse {
  items: WorkflowDailyRateRow[];
}

export interface DiagnosticsConditionTrace {
  kind: 'leaf' | 'all' | 'any' | 'not' | 'empty' | 'invalid';
  result: boolean;
  op?: string | null;
  path?: string | null;
  value?: unknown;
  resolved_value?: unknown;
  missing?: boolean;
  children?: DiagnosticsConditionTrace[];
  error?: string | null;
}

export interface WorkflowDiagnosticsEntry {
  workflow_id: string;
  workflow_name: string;
  eligible: boolean;
  reason: string | null;
  trigger_condition_trace: DiagnosticsConditionTrace | null;
  re_enrollment_decision: 'allowed' | 'blocked_once' | 'blocked_daily' | 'n/a';
  resolved_context: Record<string, unknown>;
}

export interface WorkflowDiagnosticsResponse {
  contact_id: string;
  event_type: string;
  synthesised_payload: boolean;
  entries: WorkflowDiagnosticsEntry[];
}

export interface WorkflowRunDetailStep {
  id: string;
  run_id: string;
  node_id: string;
  step_index: number;
  status: WorkflowStepRunStatus;
  started_at: string;
  completed_at: string | null;
  output_edge_label: string | null;
  skip_reason: string | null;
  payload: Record<string, unknown>;
  error: string | null;
  node_label: string;
  node_type: string;
}

export interface WorkflowRunDetailResponse {
  run: WorkflowRunRead;
  workflow_id: string;
  workflow_name: string;
  steps: WorkflowRunDetailStep[];
}

// --- tasks/workflow-scheduling Step 4: Schedules ----------------------

export type ScheduleKind = 'once' | 'daily' | 'weekly' | 'monthly' | 'interval' | 'cron';
export type OnMissedPolicy = 'skip' | 'run_once' | 'backfill_all';
export type ConcurrencyPolicy = 'allow' | 'forbid' | 'replace';
export type DeactivationReason =
  | 'manual'
  | 'ended'
  | 'max_runs'
  | 'end_at'
  | 'consecutive_empty'
  | 'recurrence_timeout'
  | 'recurrence_invalid'
  | 'contact_deleted'
  | 'admin_edit_past_end_at';

export interface Schedule {
  id: string;
  org_id: string;
  workflow_id: string;
  contact_id: string | null;
  name: string;
  schedule_kind: ScheduleKind;
  config_json: Record<string, unknown>;
  timezone: string;
  starts_at: string;
  end_at: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  runs_completed: number;
  max_runs: number | null;
  active: boolean;
  deactivation_reason: DeactivationReason | null;
  on_missed: OnMissedPolicy;
  concurrency_policy: ConcurrencyPolicy;
  consecutive_empty_fires: number;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreatePayload {
  name: string;
  schedule_kind: ScheduleKind;
  config_json: Record<string, unknown>;
  timezone?: string | null;
  starts_at: string;
  end_at?: string | null;
  max_runs?: number | null;
  contact_id?: string | null;
  on_missed?: OnMissedPolicy;
  concurrency_policy?: ConcurrencyPolicy;
}

export interface ScheduleUpdatePayload {
  name?: string;
  schedule_kind?: ScheduleKind;
  config_json?: Record<string, unknown>;
  timezone?: string;
  starts_at?: string;
  end_at?: string | null;
  max_runs?: number | null;
  contact_id?: string | null;
  on_missed?: OnMissedPolicy;
  concurrency_policy?: ConcurrencyPolicy;
}

export interface SchedulePreviewPayload {
  schedule_kind: ScheduleKind;
  config_json: Record<string, unknown>;
  timezone: string;
  starts_at: string;
}

export interface SchedulePreviewResponse {
  fires: string[];
}

// --- Step 18: A/B testing ---------------------------------------------

export type ABWinnerMetric = 'goal_conversion' | 'reply_rate' | 'open_rate' | 'custom';

export interface PairABRequest {
  sibling_id: string;
  holdback_seconds: number;
  metric?: ABWinnerMetric;
  min_runs_per_variant?: number;
}

export interface ABStatsResponse {
  workflow_id: string;
  sibling_workflow_id: string;
  a_workflow_id: string;
  b_workflow_id: string;
  a_total_runs: number;
  a_goal_runs: number;
  a_rate: number;
  b_total_runs: number;
  b_goal_runs: number;
  b_rate: number;
  p_value: number | null;
  winner: 'a' | 'b' | 'inconclusive';
  holdback_until: string | null;
  decided_at: string | null;
  min_runs_per_variant: number;
}

@Injectable({ providedIn: 'root' })
export class WorkflowsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/workflows`;
  // tasks/workflow-scheduling Step 4 — schedule endpoints hang off a
  // sibling `/api/v1/schedules/*` prefix (per Step 3 wiring). The
  // nested list/create routes live under /workflows/{id}/schedules.
  private readonly schedulesBase = `${environment.apiBaseUrl}/schedules`;

  // --- Workflow CRUD ------------------------------------------------

  list(query: WorkflowListQuery = {}): Observable<WorkflowListResponse> {
    const params = buildHttpParams({
      status: query.status,
      category: query.category,
      folder_id: query.folder_id,
      q: query.q,
      has_schedule: query.has_schedule,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<WorkflowListResponse>(this.base, { params });
  }

  get(id: string): Observable<WorkflowRead> {
    return this.http.get<WorkflowRead>(`${this.base}/${id}`);
  }

  create(payload: WorkflowCreatePayload): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(this.base, payload);
  }

  patch(id: string, payload: WorkflowUpdatePayload): Observable<WorkflowRead> {
    return this.http.patch<WorkflowRead>(`${this.base}/${id}`, payload);
  }

  archive(id: string): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${id}/archive`, {});
  }

  activate(id: string): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${id}/activate`, {});
  }

  pause(id: string): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${id}/pause`, {});
  }

  clone(id: string, name: string): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${id}/clone`, { name });
  }

  testFire(id: string, payload: WorkflowTestFireRequest): Observable<WorkflowTestFireResponse> {
    return this.http.post<WorkflowTestFireResponse>(`${this.base}/${id}/test-fire`, payload);
  }

  // --- Step 16: gallery + clone-from-gallery -----------------------

  listGallery(): Observable<WorkflowGalleryListResponse> {
    return this.http.get<WorkflowGalleryListResponse>(`${this.base}/gallery`);
  }

  cloneFromGallery(
    templateId: string,
    payload: WorkflowGalleryCloneRequest,
  ): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/gallery/${templateId}/clone`, payload);
  }

  // --- Step 17: version history + rollback + import / export ---------

  listVersions(
    workflowId: string,
    query: { limit?: number; offset?: number } = {},
  ): Observable<WorkflowVersionListResponse> {
    const params = buildHttpParams({
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<WorkflowVersionListResponse>(`${this.base}/${workflowId}/versions`, {
      params,
    });
  }

  getVersion(workflowId: string, version: number): Observable<WorkflowVersionDetail> {
    return this.http.get<WorkflowVersionDetail>(`${this.base}/${workflowId}/versions/${version}`);
  }

  rollback(workflowId: string, payload: WorkflowRollbackRequest): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${workflowId}/rollback`, payload);
  }

  exportWorkflow(workflowId: string): Observable<WorkflowExportBody> {
    return this.http.get<WorkflowExportBody>(`${this.base}/${workflowId}/export`);
  }

  importWorkflow(payload: WorkflowImportRequest): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/import`, payload);
  }

  // --- Step 18: A/B testing ----------------------------------------

  pairAB(workflowId: string, payload: PairABRequest): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${workflowId}/pair-ab`, payload);
  }

  unpairAB(workflowId: string): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/${workflowId}/unpair-ab`, {});
  }

  getABStats(workflowId: string): Observable<ABStatsResponse> {
    return this.http.get<ABStatsResponse>(`${this.base}/${workflowId}/ab-stats`);
  }

  // --- Step 19: analytics + diagnostics + run-detail -----------------

  getAnalytics(
    workflowId: string,
    query: { since?: string; until?: string } = {},
  ): Observable<WorkflowAnalyticsResponse> {
    const params = buildHttpParams({
      since: query.since,
      until: query.until,
    });
    return this.http.get<WorkflowAnalyticsResponse>(`${this.base}/${workflowId}/analytics`, {
      params,
    });
  }

  getDailyRate(workflowId: string, days = 30): Observable<WorkflowDailyRateResponse> {
    const params = buildHttpParams({ days });
    return this.http.get<WorkflowDailyRateResponse>(`${this.base}/${workflowId}/analytics/daily`, {
      params,
    });
  }

  traceDiagnostics(query: {
    contact_id: string;
    event_type: string;
  }): Observable<WorkflowDiagnosticsResponse> {
    const params = buildHttpParams({
      contact_id: query.contact_id,
      event_type: query.event_type,
    });
    return this.http.get<WorkflowDiagnosticsResponse>(`${this.base}/diagnostics/trace`, { params });
  }

  getRunDetail(runId: string): Observable<WorkflowRunDetailResponse> {
    return this.http.get<WorkflowRunDetailResponse>(`${this.base}/runs/${runId}`);
  }

  // --- Folders ------------------------------------------------------

  listFolders(): Observable<WorkflowFolder[]> {
    return this.http.get<WorkflowFolder[]>(`${this.base}/folders`);
  }

  createFolder(payload: WorkflowFolderCreatePayload): Observable<WorkflowFolder> {
    return this.http.post<WorkflowFolder>(`${this.base}/folders`, payload);
  }

  patchFolder(id: string, payload: WorkflowFolderUpdatePayload): Observable<WorkflowFolder> {
    return this.http.patch<WorkflowFolder>(`${this.base}/folders/${id}`, payload);
  }

  deleteFolder(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/folders/${id}`);
  }

  // --- Runs ---------------------------------------------------------

  listRuns(
    workflowId: string,
    query: WorkflowRunListQuery = {},
  ): Observable<WorkflowRunListResponse> {
    const params = buildHttpParams({
      status: query.status,
      contact_id: query.contact_id,
      limit: query.limit,
      offset: query.offset,
    });
    return this.http.get<WorkflowRunListResponse>(`${this.base}/${workflowId}/runs`, { params });
  }

  getRun(runId: string): Observable<WorkflowRunRead> {
    return this.http.get<WorkflowRunRead>(`${this.base}/runs/${runId}`);
  }

  listRunSteps(runId: string): Observable<WorkflowStepRunRead[]> {
    return this.http.get<WorkflowStepRunRead[]>(`${this.base}/runs/${runId}/steps`);
  }

  // --- tasks/workflow-scheduling Step 4: Schedules -----------------

  listSchedulesForWorkflow(workflowId: string): Observable<Schedule[]> {
    return this.http.get<Schedule[]>(`${this.base}/${workflowId}/schedules`);
  }

  createSchedule(workflowId: string, payload: ScheduleCreatePayload): Observable<Schedule> {
    return this.http.post<Schedule>(`${this.base}/${workflowId}/schedules`, payload);
  }

  getSchedule(scheduleId: string): Observable<Schedule> {
    return this.http.get<Schedule>(`${this.schedulesBase}/${scheduleId}`);
  }

  /**
   * PATCH a schedule. ``etag`` is the ``updated_at`` returned on the
   * last GET / mutation — sent verbatim as ``If-Match``. Server 428
   * on missing, 409 on stale. Callers should catch 409 and re-fetch.
   */
  updateSchedule(
    scheduleId: string,
    etag: string,
    payload: ScheduleUpdatePayload,
  ): Observable<Schedule> {
    return this.http.patch<Schedule>(`${this.schedulesBase}/${scheduleId}`, payload, {
      headers: { 'If-Match': etag },
    });
  }

  deleteSchedule(scheduleId: string): Observable<void> {
    return this.http.delete<void>(`${this.schedulesBase}/${scheduleId}`);
  }

  pauseSchedule(scheduleId: string): Observable<Schedule> {
    return this.http.post<Schedule>(`${this.schedulesBase}/${scheduleId}/pause`, {});
  }

  resumeSchedule(scheduleId: string): Observable<Schedule> {
    return this.http.post<Schedule>(`${this.schedulesBase}/${scheduleId}/resume`, {});
  }

  previewSchedule(payload: SchedulePreviewPayload): Observable<SchedulePreviewResponse> {
    return this.http.post<SchedulePreviewResponse>(`${this.schedulesBase}/preview`, payload);
  }

  /**
   * Pause every ACTIVE schedule attached to a workflow. Sequential
   * (one POST per schedule) so per-schedule audit rows land — not a
   * bulk DB update. Returns a summary tuple; failures are counted
   * but don't halt the run. Emits the summary once when the loop
   * completes.
   */
  pauseAllSchedulesForWorkflow(
    workflowId: string,
  ): Observable<{ paused: number; skipped: number; errored: number }> {
    return new Observable((observer) => {
      let cancelled = false;
      (async () => {
        try {
          const schedules = await new Promise<Schedule[]>((resolve, reject) => {
            this.listSchedulesForWorkflow(workflowId).subscribe({
              next: resolve,
              error: reject,
            });
          });
          let paused = 0;
          let skipped = 0;
          let errored = 0;
          for (const s of schedules) {
            if (cancelled) return;
            if (!s.active) {
              skipped += 1;
              continue;
            }
            try {
              await new Promise<Schedule>((resolve, reject) => {
                this.pauseSchedule(s.id).subscribe({ next: resolve, error: reject });
              });
              paused += 1;
            } catch {
              errored += 1;
            }
          }
          observer.next({ paused, skipped, errored });
          observer.complete();
        } catch (err) {
          observer.error(err);
        }
      })();
      return () => {
        cancelled = true;
      };
    });
  }

  /** Symmetric counterpart of :func:`pauseAllSchedulesForWorkflow`.
   *  Only touches rows that are currently paused (skips ended /
   *  naturally-exhausted rows because the service-layer resume path
   *  would 422 them). */
  resumeAllSchedulesForWorkflow(
    workflowId: string,
  ): Observable<{ resumed: number; skipped: number; errored: number }> {
    return new Observable((observer) => {
      let cancelled = false;
      const terminal = new Set(['ended', 'max_runs', 'end_at']);
      (async () => {
        try {
          const schedules = await new Promise<Schedule[]>((resolve, reject) => {
            this.listSchedulesForWorkflow(workflowId).subscribe({
              next: resolve,
              error: reject,
            });
          });
          let resumed = 0;
          let skipped = 0;
          let errored = 0;
          for (const s of schedules) {
            if (cancelled) return;
            if (s.active) {
              skipped += 1;
              continue;
            }
            if (s.deactivation_reason && terminal.has(s.deactivation_reason)) {
              skipped += 1;
              continue;
            }
            try {
              await new Promise<Schedule>((resolve, reject) => {
                this.resumeSchedule(s.id).subscribe({ next: resolve, error: reject });
              });
              resumed += 1;
            } catch {
              errored += 1;
            }
          }
          observer.next({ resumed, skipped, errored });
          observer.complete();
        } catch (err) {
          observer.error(err);
        }
      })();
      return () => {
        cancelled = true;
      };
    });
  }
}
