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
export type WorkflowRunOutcome =
  | 'goal_reached'
  | 'completed'
  | 'canceled'
  | 'errored'
  | null;
export type WorkflowStepRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'skipped'
  | 'errored';

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
  created_at: string;
  updated_at: string;
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


@Injectable({ providedIn: 'root' })
export class WorkflowsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/workflows`;

  // --- Workflow CRUD ------------------------------------------------

  list(query: WorkflowListQuery = {}): Observable<WorkflowListResponse> {
    const params = buildHttpParams({
      status: query.status,
      category: query.category,
      folder_id: query.folder_id,
      q: query.q,
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

  testFire(
    id: string,
    payload: WorkflowTestFireRequest,
  ): Observable<WorkflowTestFireResponse> {
    return this.http.post<WorkflowTestFireResponse>(
      `${this.base}/${id}/test-fire`,
      payload,
    );
  }

  // --- Step 16: gallery + clone-from-gallery -----------------------

  listGallery(): Observable<WorkflowGalleryListResponse> {
    return this.http.get<WorkflowGalleryListResponse>(
      `${this.base}/gallery`,
    );
  }

  cloneFromGallery(
    templateId: string,
    payload: WorkflowGalleryCloneRequest,
  ): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(
      `${this.base}/gallery/${templateId}/clone`,
      payload,
    );
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
    return this.http.get<WorkflowVersionListResponse>(
      `${this.base}/${workflowId}/versions`,
      { params },
    );
  }

  getVersion(
    workflowId: string,
    version: number,
  ): Observable<WorkflowVersionDetail> {
    return this.http.get<WorkflowVersionDetail>(
      `${this.base}/${workflowId}/versions/${version}`,
    );
  }

  rollback(
    workflowId: string,
    payload: WorkflowRollbackRequest,
  ): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(
      `${this.base}/${workflowId}/rollback`,
      payload,
    );
  }

  exportWorkflow(workflowId: string): Observable<WorkflowExportBody> {
    return this.http.get<WorkflowExportBody>(
      `${this.base}/${workflowId}/export`,
    );
  }

  importWorkflow(
    payload: WorkflowImportRequest,
  ): Observable<WorkflowRead> {
    return this.http.post<WorkflowRead>(`${this.base}/import`, payload);
  }

  // --- Folders ------------------------------------------------------

  listFolders(): Observable<WorkflowFolder[]> {
    return this.http.get<WorkflowFolder[]>(`${this.base}/folders`);
  }

  createFolder(
    payload: WorkflowFolderCreatePayload,
  ): Observable<WorkflowFolder> {
    return this.http.post<WorkflowFolder>(`${this.base}/folders`, payload);
  }

  patchFolder(
    id: string,
    payload: WorkflowFolderUpdatePayload,
  ): Observable<WorkflowFolder> {
    return this.http.patch<WorkflowFolder>(
      `${this.base}/folders/${id}`,
      payload,
    );
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
    return this.http.get<WorkflowRunListResponse>(
      `${this.base}/${workflowId}/runs`,
      { params },
    );
  }

  getRun(runId: string): Observable<WorkflowRunRead> {
    return this.http.get<WorkflowRunRead>(`${this.base}/runs/${runId}`);
  }

  listRunSteps(runId: string): Observable<WorkflowStepRunRead[]> {
    return this.http.get<WorkflowStepRunRead[]>(
      `${this.base}/runs/${runId}/steps`,
    );
  }
}
