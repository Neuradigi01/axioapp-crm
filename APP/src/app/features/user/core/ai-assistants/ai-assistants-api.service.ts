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
import { HttpClient, HttpEvent, HttpParams, HttpRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import {
  AiProviderKey,
  AiProvidersApiService,
} from '../settings/integrations/ai-providers-api.service';

export type AiAssistantStatus = 'draft' | 'active' | 'archived';

export type LeadCaptureMode = 'off' | 'detect_email' | 'ask_at_turn';

/** Channels an assistant is bound to auto-answer on. Matches the
 *  backend ``AiAssistantChannel`` enum in
 *  ``core/ai_assistants/models.py`` — new channels ship here first,
 *  then the JSONB storage accepts them without a migration. */
export type AiAssistantChannel = 'ai_widget' | 'whatsapp' | 'email';

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
  lead_capture_mode: LeadCaptureMode;
  lead_capture_turn_n: number;
  lead_capture_message: string | null;
  version: number;
  created_by_user_id: string | null;
  interface_config: Record<string, unknown>;
  styling_config: Record<string, unknown>;
  bound_channels: AiAssistantChannel[];
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
  bound_channels: AiAssistantChannel[];
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
  lead_capture_mode?: LeadCaptureMode;
  lead_capture_turn_n?: number;
  lead_capture_message?: string | null;
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
  lead_capture_mode?: LeadCaptureMode;
  lead_capture_turn_n?: number;
  lead_capture_message?: string | null;
  interface_config?: Record<string, unknown>;
  styling_config?: Record<string, unknown>;
  bound_channels?: AiAssistantChannel[];
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

  activate(id: string): Observable<AiAssistant> {
    return this.http.post<AiAssistant>(`${this.base}/${id}/activate`, {});
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

  // --- Knowledge source (Step 10 backend / Step 11 UI) ------------

  listKnowledge(assistantId: string): Observable<AiAssistantKnowledgeRow[]> {
    return this.http.get<AiAssistantKnowledgeRow[]>(`${this.base}/${assistantId}/knowledge`);
  }

  /** File upload with per-chunk progress. Consumers ``subscribe`` and
   *  branch on ``event.type``: ``UploadProgress`` events surface the
   *  0-100% XHR upload metric; the terminal ``Response`` event carries
   *  the created row + dedup flag. */
  uploadKnowledgeFile(
    assistantId: string,
    file: File,
  ): Observable<HttpEvent<KnowledgeCreateResponse>> {
    const form = new FormData();
    form.append('file', file, file.name);
    const req = new HttpRequest('POST', `${this.base}/${assistantId}/knowledge/file`, form, {
      reportProgress: true,
    });
    return this.http.request<KnowledgeCreateResponse>(req);
  }

  addKnowledgeText(
    assistantId: string,
    payload: KnowledgeTextPayload,
  ): Observable<KnowledgeCreateResponse> {
    return this.http.post<KnowledgeCreateResponse>(
      `${this.base}/${assistantId}/knowledge/text`,
      payload,
    );
  }

  addKnowledgeUrl(
    assistantId: string,
    payload: KnowledgeUrlPayload,
  ): Observable<KnowledgeCreateResponse> {
    return this.http.post<KnowledgeCreateResponse>(
      `${this.base}/${assistantId}/knowledge/url`,
      payload,
    );
  }

  cancelKnowledge(assistantId: string, knowledgeId: string): Observable<AiAssistantKnowledgeRow> {
    return this.http.post<AiAssistantKnowledgeRow>(
      `${this.base}/${assistantId}/knowledge/${knowledgeId}/cancel`,
      {},
    );
  }

  deleteKnowledge(assistantId: string, knowledgeId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${assistantId}/knowledge/${knowledgeId}`);
  }

  replaceKnowledgeFile(
    assistantId: string,
    knowledgeId: string,
    file: File,
  ): Observable<HttpEvent<KnowledgeCreateResponse>> {
    const form = new FormData();
    form.append('file', file, file.name);
    const req = new HttpRequest(
      'POST',
      `${this.base}/${assistantId}/knowledge/${knowledgeId}/replace`,
      form,
      { reportProgress: true },
    );
    return this.http.request<KnowledgeCreateResponse>(req);
  }

  // --- Embed keys (Step 15) --------------------------------------------

  /** List embed keys bound to one assistant. Never returns plaintext. */
  listEmbedKeys(assistantId: string): Observable<EmbedKeyRow[]> {
    return this.http.get<EmbedKeyRow[]>(
      `${environment.apiBaseUrl}/embed/ai-assistants/${assistantId}/keys`,
    );
  }

  /** Issue a new embed key. The ``secret`` on the returned envelope
   *  appears ONCE — surface it in the snippet modal + let the
   *  operator copy before navigating away. */
  issueEmbedKey(
    assistantId: string,
    payload: EmbedKeyIssuePayload,
  ): Observable<EmbedKeyIssueResponse> {
    return this.http.post<EmbedKeyIssueResponse>(
      `${environment.apiBaseUrl}/embed/ai-assistants/${assistantId}/keys`,
      payload,
    );
  }

  /** Rotate: issues a fresh key + revokes the old one (with optional
   *  grace window in days). */
  rotateEmbedKey(keyId: string, graceDays: number = 0): Observable<EmbedKeyIssueResponse> {
    return this.http.post<EmbedKeyIssueResponse>(
      `${environment.apiBaseUrl}/embed/keys/${keyId}/rotate`,
      {},
      { params: new HttpParams().set('grace_days', String(graceDays)) },
    );
  }

  /** Hard-revoke + close every in-flight SSE stream for this key. */
  revokeEmbedKeyNow(keyId: string): Observable<void> {
    return this.http.post<void>(`${environment.apiBaseUrl}/embed/keys/${keyId}/revoke-now`, {});
  }

  // --- Analytics (Step 16) ------------------------------------------

  /** Message count + cost + top-20 questions for one assistant over
   *  ``windowDays`` (default 30). */
  getAnalytics(
    assistantId: string,
    windowDays: number = 30,
  ): Observable<AiAssistantAnalyticsResponse> {
    return this.http.get<AiAssistantAnalyticsResponse>(`${this.base}/${assistantId}/analytics`, {
      params: new HttpParams().set('window_days', String(windowDays)),
    });
  }

  // --- Profile picture (Step 13) ------------------------------------

  /** Upload the header profile picture. PNG / JPEG / WebP, < 2 MB.
   *  Backend refuses SVG explicitly. Returns the served URL — the
   *  caller writes it onto ``styling_config.header_profile_picture_url``
   *  in the local form-state store so the preview renders it
   *  without a re-fetch. */
  uploadProfilePicture(assistantId: string, file: File): Observable<ProfilePictureResponse> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<ProfilePictureResponse>(
      `${this.base}/${assistantId}/profile-picture`,
      form,
    );
  }

  deleteProfilePicture(assistantId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${assistantId}/profile-picture`);
  }
}

export interface ProfilePictureResponse {
  url: string;
}

// --- Embed key shapes (Step 15) --------------------------------------

export interface EmbedKeyRow {
  id: string;
  org_id: string;
  name: string | null;
  prefix: string;
  resource_type: string;
  resource_id: string | null;
  allowed_origins: string[];
  rate_limit_per_hour: number;
  last_used_at: string | null;
  revoked_at: string | null;
  grace_expires_at: string | null;
  created_at: string;
}

export interface EmbedKeyIssueResponse {
  id: string;
  name: string | null;
  prefix: string;
  /** Plaintext key — appears ONCE. Never re-fetched. */
  secret: string;
  created_at: string;
}

export interface EmbedKeyIssuePayload {
  name?: string | null;
  allowed_origins?: string[];
  rate_limit_per_hour?: number | null;
}

// --- Analytics (Step 16) ---------------------------------------------

export interface TopQuestionRow {
  normalized: string;
  count: number;
}

export interface AiAssistantAnalyticsResponse {
  window_days: number;
  message_count: number;
  total_cost_usd: string;
  top_questions: TopQuestionRow[];
}

// --- Knowledge shapes (mirror ``schemas.py``) ----------------------

export type KnowledgeSourceType = 'file' | 'text' | 'url';

export type KnowledgeStatus =
  | 'pending'
  | 'processing'
  | 'ready'
  | 'failed_no_text'
  | 'failed_stuck'
  | 'failed_ingest'
  | 'pending_delete'
  | 'pending_cancel';

export interface AiAssistantKnowledgeRow {
  id: string;
  assistant_id: string;
  source_type: KnowledgeSourceType;
  original_filename: string | null;
  url: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  status: KnowledgeStatus;
  status_message: string | null;
  progress_pct: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCreateResponse {
  duplicate: boolean;
  knowledge: AiAssistantKnowledgeRow;
}

export interface KnowledgeTextPayload {
  title: string;
  body_text: string;
}

export interface KnowledgeUrlPayload {
  title: string;
  url: string;
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
