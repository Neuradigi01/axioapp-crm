import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/**
 * Keyword-rule automation API client
 * (whatsapp-platform-upgrade Step 17).
 *
 * Mirrors the Step-17 backend at
 * `/api/v1/integrations/whatsapp/keyword-rules`.
 */

export type KeywordMatchType = 'contains' | 'exact' | 'regex';

export type KeywordActionType =
  | 'reply_text'
  | 'reply_template'
  | 'tag_conversation'
  | 'assign_to_user'
  | 'escalate_to_ai';

export interface KeywordActionPayload {
  action_type: KeywordActionType;
  action_config: Record<string, unknown>;
  position: number;
}

export interface KeywordAction {
  id: string;
  action_type: KeywordActionType;
  action_config: Record<string, unknown>;
  position: number;
}

export interface KeywordRule {
  id: string;
  name: string;
  keywords: string[];
  match_type: KeywordMatchType;
  enabled: boolean;
  priority: number;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  actions: KeywordAction[];
}

export interface KeywordRuleUpsert {
  name: string;
  keywords: string[];
  match_type: KeywordMatchType;
  enabled: boolean;
  priority: number;
  actions: KeywordActionPayload[];
}

export interface RuleTestResponse {
  matched_rule_id: string | null;
  matched_rule_name: string | null;
  actions: KeywordAction[];
}

@Injectable({ providedIn: 'root' })
export class WhatsAppAutomationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/keyword-rules`;

  list(): Observable<KeywordRule[]> {
    return this.http.get<KeywordRule[]>(this.base);
  }

  get(id: string): Observable<KeywordRule> {
    return this.http.get<KeywordRule>(`${this.base}/${id}`);
  }

  create(payload: KeywordRuleUpsert): Observable<KeywordRule> {
    return this.http.post<KeywordRule>(this.base, payload);
  }

  update(id: string, payload: KeywordRuleUpsert): Observable<KeywordRule> {
    return this.http.patch<KeywordRule>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** Reassign `priority` based on the new id ordering. First id =
   *  priority 10, second = 20, etc. */
  reorder(ruleIds: string[]): Observable<KeywordRule[]> {
    return this.http.post<KeywordRule[]>(`${this.base}/reorder`, {
      rule_ids: ruleIds,
    });
  }

  /** Dry-run — evaluate `text` against the active rules. Returns the
   *  first match + its projected actions. Does NOT send / tag /
   *  assign anything. */
  test(text: string): Observable<RuleTestResponse> {
    return this.http.post<RuleTestResponse>(`${this.base}/test`, { text });
  }

  // --- Assignment rules (whatsapp-platform-upgrade Step 18) ---------

  private readonly assignmentBase = `${environment.apiBaseUrl}/integrations/whatsapp/assignment-rules`;

  listAssignmentRules(): Observable<AssignmentRule[]> {
    return this.http.get<AssignmentRule[]>(this.assignmentBase);
  }

  createAssignmentRule(payload: AssignmentRuleUpsert): Observable<AssignmentRule> {
    return this.http.post<AssignmentRule>(this.assignmentBase, payload);
  }

  updateAssignmentRule(id: string, payload: AssignmentRuleUpsert): Observable<AssignmentRule> {
    return this.http.patch<AssignmentRule>(`${this.assignmentBase}/${id}`, payload);
  }

  deleteAssignmentRule(id: string): Observable<void> {
    return this.http.delete<void>(`${this.assignmentBase}/${id}`);
  }

  reorderAssignmentRules(ruleIds: string[]): Observable<AssignmentRule[]> {
    return this.http.post<AssignmentRule[]>(`${this.assignmentBase}/reorder`, {
      rule_ids: ruleIds,
    });
  }

  // --- AI settings (whatsapp-platform-upgrade Step 19) --------------

  private readonly aiBase = `${environment.apiBaseUrl}/integrations/whatsapp/ai`;

  getAISettings(): Observable<AISettings> {
    return this.http.get<AISettings>(`${this.aiBase}/settings`);
  }

  patchAISettings(payload: AISettingsPatch): Observable<AISettings> {
    return this.http.patch<AISettings>(`${this.aiBase}/settings`, payload);
  }
}

// --- Step 18 types -------------------------------------------------

export type AssignmentStrategy = 'round_robin' | 'load_balanced' | 'tag_based' | 'team_based';

export interface AssignmentRule {
  id: string;
  name: string;
  strategy: AssignmentStrategy;
  config: Record<string, unknown>;
  enabled: boolean;
  priority: number;
  skip_outside_hours: boolean;
  last_assigned_user_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssignmentRuleUpsert {
  name: string;
  strategy: AssignmentStrategy;
  config: Record<string, unknown>;
  enabled: boolean;
  priority: number;
  skip_outside_hours: boolean;
}

// --- Step 19 — AI settings ----------------------------------------

export interface AISettings {
  ai_handling_default_enabled: boolean;
  ai_confidence_threshold: number;
  ai_handover_keywords: string[];
  ai_system_prompt: string | null;
}

export interface AISettingsPatch {
  ai_handling_default_enabled?: boolean;
  ai_confidence_threshold?: number;
  ai_handover_keywords?: string[];
  ai_system_prompt?: string | null;
}
