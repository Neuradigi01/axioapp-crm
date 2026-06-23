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
}
