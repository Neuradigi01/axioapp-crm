import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

/**
 * Chatbots API client (tasks/chatbot-builder Step 12).
 *
 * Wraps the Step-3 REST endpoints under `/api/v1/chatbots` +
 * Step-6 test-fire + Step-11 signed reply URLs (URLs served
 * separately at `/r/*`).
 *
 * All reads gated on `chatbots.view`; create/patch/pause gated
 * on `chatbots.edit`; publish/rollback on `chatbots.publish`;
 * archive on `chatbots.delete`. The list page hides mutation
 * affordances behind the permission checks at render time so the
 * UI doesn't dangle un-clickable buttons.
 */

export type ChatbotStatus = 'draft' | 'live' | 'paused' | 'archived';
export type TriggerChannel = 'any' | 'whatsapp' | 'email';
export type TriggerMode = 'any' | 'keyword' | 'regex';

export interface TriggerConfig {
  channel: TriggerChannel;
  mode: TriggerMode;
  keywords: string[];
  regex_pattern: string | null;
  case_sensitive: boolean;
  first_message_only: boolean;
}

export interface ChatbotGraph {
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

export interface ChatbotListItem {
  id: string;
  name: string;
  description: string | null;
  category: string;
  folder_id: string | null;
  status: ChatbotStatus;
  priority: number;
  trigger_config: TriggerConfig;
  version_number: number;
  updated_at: string;
}

export interface ChatbotRead {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  category: string;
  folder_id: string | null;
  status: ChatbotStatus;
  priority: number;
  trigger_config: TriggerConfig;
  graph: ChatbotGraph;
  version_number: number;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ChatbotCreatePayload {
  name: string;
  description?: string | null;
  category?: string;
  folder_id?: string | null;
  priority?: number;
  trigger_config?: TriggerConfig;
  graph?: ChatbotGraph;
}

export interface ChatbotUpdatePayload {
  expected_version: number;
  name?: string | null;
  description?: string | null;
  category?: string | null;
  folder_id?: string | null;
  priority?: number | null;
  trigger_config?: TriggerConfig | null;
  graph?: ChatbotGraph | null;
  change_note?: string | null;
}

export interface ChatbotVersionRead {
  id: string;
  chatbot_id: string;
  version_number: number;
  graph: ChatbotGraph;
  trigger_config: TriggerConfig;
  change_note: string | null;
  created_by_user_id: string | null;
  created_at: string;
}

export interface NodeHitCount {
  node_id: string;
  node_type: string;
  executions: number;
}

export interface ChatbotStats {
  total_runs: number;
  running: number;
  parked: number;
  completed: number;
  canceled: number;
  errored: number;
  completion_rate: number;
  top_nodes: NodeHitCount[];
}

export interface SaveTargetEntry {
  entity: string;
  field_key: string;
  display_label: string;
  format: string;
  is_custom: boolean;
  qualified_key: string;
}

export interface TestFireStep {
  node_id: string;
  node_type: string;
  status: string;
  output_edge_label: string | null;
  skip_reason: string | null;
  error: string | null;
  output: Record<string, unknown>;
}

export interface TestFireResponse {
  run_id: string;
  final_status: string;
  canceled_reason: string | null;
  error: string | null;
  steps: TestFireStep[];
}

export interface TestFireRequest {
  simulated_inbound_text: string;
  simulated_channel?: 'whatsapp' | 'email';
  simulated_contact_id?: string | null;
  simulated_conversation_id?: string | null;
  simulated_is_first_message?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ChatbotsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/chatbots`;

  list(params?: {
    status?: ChatbotStatus | '';
    category?: string;
    folderId?: string | null;
    q?: string;
    limit?: number;
    offset?: number;
  }): Observable<ChatbotListItem[]> {
    const query: Record<string, string | number> = {};
    if (params?.status) query['status'] = params.status;
    if (params?.category) query['category'] = params.category;
    if (params?.folderId) query['folder_id'] = params.folderId;
    if (params?.q) query['q'] = params.q;
    if (params?.limit !== undefined) query['limit'] = params.limit;
    if (params?.offset !== undefined) query['offset'] = params.offset;
    return this.http.get<ChatbotListItem[]>(this.base, { params: query as Record<string, string> });
  }

  get(id: string): Observable<ChatbotRead> {
    return this.http.get<ChatbotRead>(`${this.base}/${id}`);
  }

  create(payload: ChatbotCreatePayload): Observable<ChatbotRead> {
    return this.http.post<ChatbotRead>(this.base, payload);
  }

  update(id: string, payload: ChatbotUpdatePayload): Observable<ChatbotRead> {
    return this.http.patch<ChatbotRead>(`${this.base}/${id}`, payload);
  }

  publish(id: string): Observable<ChatbotRead> {
    return this.http.post<ChatbotRead>(`${this.base}/${id}/publish`, {});
  }

  pause(id: string): Observable<ChatbotRead> {
    return this.http.post<ChatbotRead>(`${this.base}/${id}/pause`, {});
  }

  archive(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  listVersions(id: string, limit = 50): Observable<ChatbotVersionRead[]> {
    return this.http.get<ChatbotVersionRead[]>(`${this.base}/${id}/versions`, {
      params: { limit },
    });
  }

  getStats(id: string): Observable<ChatbotStats> {
    return this.http.get<ChatbotStats>(`${this.base}/${id}/stats`);
  }

  rollback(id: string, versionId: string): Observable<ChatbotRead> {
    return this.http.post<ChatbotRead>(`${this.base}/${id}/versions/${versionId}/rollback`, {});
  }

  saveTargets(entity: string): Observable<SaveTargetEntry[]> {
    return this.http.get<SaveTargetEntry[]>(`${this.base}/save-targets`, {
      params: { entity },
    });
  }

  testFire(id: string, payload: TestFireRequest): Observable<TestFireResponse> {
    return this.http.post<TestFireResponse>(`${this.base}/${id}/test-fire`, payload);
  }

  /** Step 15 — bot export (returns portable envelope). */
  export(id: string): Observable<ChatbotExportEnvelope> {
    return this.http.get<ChatbotExportEnvelope>(`${this.base}/${id}/export`);
  }

  /** Step 15 — bot import (creates new bot from envelope). */
  import(payload: ChatbotImportRequest): Observable<ChatbotImportResult> {
    return this.http.post<ChatbotImportResult>(`${this.base}/import`, payload);
  }
}

// --- Step 15 export / import types ---------------------------------------

export interface ChatbotExportEnvelope {
  chatbot_export_version: number;
  exported_at: string;
  source_org_name: string;
  bot: {
    name: string;
    description: string | null;
    category: string;
    priority: number;
    trigger_config: TriggerConfig;
    graph: ChatbotGraph;
    referenced_custom_fields: Array<{ entity: string; field_key: string }>;
    referenced_templates: Array<{ template_id: string }>;
  };
}

export interface ChatbotImportRequest {
  envelope: ChatbotExportEnvelope;
  name_override?: string | null;
}

export interface ChatbotImportConflict {
  kind: 'missing_custom_field' | 'missing_template' | 'name_collision';
  detail: string;
}

export interface ChatbotImportResult {
  created_bot_id: string;
  conflicts: ChatbotImportConflict[];
}
