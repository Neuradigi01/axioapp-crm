/**
 * Typed HTTP client for the AI Assistants module
 * (``tasks/ai-assistants`` Step 6 backend, Step 7 frontend).
 *
 * Mirrors ``API/src/app/core/ai_assistants/schemas.py``. Every call
 * routes through the global ``HttpClient`` which the
 * ``auth.interceptor`` decorates with ``Authorization: Bearer <jwt>``
 * and the ``retry.interceptor`` guards against transient network
 * failures on idempotent verbs.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import {
  AiProviderKey,
  AiProvidersApiService,
} from '../settings/integrations/ai-providers-api.service';

export type AiAssistantStatus = 'draft' | 'active' | 'archived';

/** Full assistant read shape (matches ``AiAssistantRead``). */
export interface AiAssistant {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  status: AiAssistantStatus;
  key_id: string;
  model: string;
  temperature: string;
  instructions: string | null;
  stop_keywords: string[];
  retry_attempts: number;
  fallback_message: string;
  allowed_domains: string[];
  output_sanitizer_enabled: boolean;
  budget_cap_override_usd: string | null;
  version: number;
  created_by_user_id: string | null;
  interface_config: Record<string, unknown>;
  styling_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Trimmed list-view shape (matches ``AiAssistantListItem``). */
export interface AiAssistantListItem {
  id: string;
  name: string;
  status: AiAssistantStatus;
  model: string;
  key_id: string;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface AiAssistantListResponse {
  items: AiAssistantListItem[];
  total: number;
  limit: number;
  offset: number;
}

/** Create payload — ``extra='forbid'`` on the backend rejects any
 *  unknown field with 422, so the client MUST NOT include ``id`` /
 *  ``org_id`` / ``version`` / ``status`` / audit cols. */
export interface AiAssistantCreatePayload {
  name: string;
  description?: string | null;
  key_id: string;
  model: string;
  temperature?: number | string;
  instructions?: string | null;
  stop_keywords?: string[];
  retry_attempts?: number;
  fallback_message?: string | null;
  allowed_domains?: string[];
  output_sanitizer_enabled?: boolean;
  budget_cap_override_usd?: number | string | null;
}

/** Update payload — ``version`` REQUIRED for optimistic-concurrency;
 *  every other field optional. Send only fields the user actually
 *  changed. */
export interface AiAssistantUpdatePayload {
  version: number;
  name?: string;
  description?: string | null;
  key_id?: string;
  model?: string;
  temperature?: number | string;
  instructions?: string | null;
  stop_keywords?: string[];
  retry_attempts?: number;
  fallback_message?: string | null;
  allowed_domains?: string[];
  output_sanitizer_enabled?: boolean;
  budget_cap_override_usd?: number | string | null;
}

@Injectable({ providedIn: 'root' })
export class AiAssistantsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/ai-assistants`;
  /** Re-export so the Create modal can populate its key select
   *  without every consumer wiring the providers service by hand. */
  readonly providers = inject(AiProvidersApiService);

  list(params?: {
    status?: AiAssistantStatus;
    search?: string;
    limit?: number;
    offset?: number;
  }): Observable<AiAssistantListResponse> {
    let httpParams = new HttpParams();
    if (params?.status) httpParams = httpParams.set('status', params.status);
    if (params?.search) httpParams = httpParams.set('search', params.search);
    if (params?.limit !== undefined) httpParams = httpParams.set('limit', params.limit);
    if (params?.offset !== undefined) httpParams = httpParams.set('offset', params.offset);
    return this.http.get<AiAssistantListResponse>(this.base, { params: httpParams });
  }

  get(id: string): Observable<AiAssistant> {
    return this.http.get<AiAssistant>(`${this.base}/${id}`);
  }

  create(payload: AiAssistantCreatePayload): Observable<AiAssistant> {
    return this.http.post<AiAssistant>(this.base, payload);
  }

  update(id: string, payload: AiAssistantUpdatePayload): Observable<AiAssistant> {
    return this.http.patch<AiAssistant>(`${this.base}/${id}`, payload);
  }

  archive(id: string): Observable<void> {
    return this.http.post<void>(`${this.base}/${id}/archive`, {});
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`, {
      params: new HttpParams().set('confirm', 'true'),
    });
  }

  /** Passthrough — the Create modal's key select needs this. */
  listProviderKeys(): Observable<AiProviderKey[]> {
    return this.providers.list();
  }

  /** Step 8 — instruction-preset templates that populate the
   *  Instructions tab dropdown. Seeded per-org at signup +
   *  backfill migration ``0204_bf_ai_prompt_templates``. Returns
   *  the envelope's ``items`` array directly so callers don't
   *  care about the wrapping shape. */
  listAiPromptPresets(): Observable<AiPromptPresetRow[]> {
    return this.http
      .get<AiPromptPresetListResponse>(`${environment.apiBaseUrl}/templates`, {
        params: new HttpParams().set('channel', 'ai_prompt').set('limit', '50'),
      })
      .pipe(map((resp) => resp.items));
  }
}

/** Trimmed shape from ``GET /templates`` — only the fields the
 *  Instructions tab actually reads. Matches the subset the
 *  templates router returns for ``channel=ai_prompt``. */
export interface AiPromptPresetRow {
  id: string;
  name: string;
  body_text: string;
}

/** ``GET /templates`` returns a paginated envelope. */
interface AiPromptPresetListResponse {
  items: AiPromptPresetRow[];
  total: number;
  limit: number;
  offset: number;
}
