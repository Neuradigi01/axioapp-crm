/**
 * Typed HTTP wrappers for the BYOK provider-key surface
 * (``tasks/ai-assistants`` Step 1 backend, Step 3 UI).
 *
 * Every call is gated server-side by ``ai_providers.manage``. The
 * frontend hides the card unless the current user's permission
 * bag includes the key; the API still enforces it (defence in
 * depth — a curious user typing the URL hits the same 403).
 *
 * Auth: routed through the global ``HttpClient`` which the
 * ``auth.interceptor`` decorates with ``Authorization: Bearer <jwt>``.
 *
 * Endpoint shape mirrors ``API/src/app/core/integrations/ai/router.py``:
 *   POST   /providers                — create key (returns masked read).
 *   GET    /providers                — list (never returns ciphertext).
 *   POST   /providers/{id}/test      — probe upstream via shared/llm.
 *   POST   /providers/reassign       — swap references K1 → K2
 *                                       (501 until Step 5 lands).
 *   DELETE /providers/{id}           — hard-delete (409 if referenced).
 *   GET    /budget                   — read caps + rollups.
 *   PATCH  /budget                   — update daily/monthly caps.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

// --- Provider keys (mirror backend AiProviderKeyRead) ------------------

export type AiProvider = 'openai' | 'anthropic' | 'google' | 'openrouter';
export type AiProviderTestStatus = 'untested' | 'success' | 'failed';

export interface AiProviderKey {
  id: string;
  provider: AiProvider;
  label: string;
  /** Last 4 chars of the plaintext API key. Never the full key. */
  last4: string;
  test_status: AiProviderTestStatus;
  test_last_at: string | null;
  test_last_error: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AiProviderKeyCreatePayload {
  provider: AiProvider;
  label?: string;
  api_key: string;
}

export interface AiProviderKeyReassignPayload {
  from_key_id: string;
  to_key_id: string;
}

/** Body returned on 409 when the same key material is already stored
 *  for this org+provider. UI shows an info banner with the existing
 *  last-4 rather than opening the reassign flow (that's a different
 *  409 shape, see below). */
export interface AiProviderKeyDuplicateError {
  reason: 'key_already_stored';
  existing_key_id: string;
  last4: string;
}

/** Body returned on 409 from DELETE when N assistants still reference
 *  the key. UI opens the reassign modal populated with `reference_count`
 *  so the operator can move all references before deleting. */
export interface AiProviderKeyReferencedError {
  reason: 'referenced_by_assistants';
  reference_count: number;
  key_id: string;
}

// --- Budget (mirror backend OrgAiCostBudgetRead) -----------------------

export interface OrgAiCostBudget {
  daily_cap_usd: string;
  monthly_cap_usd: string;
  spent_today_usd: string;
  spent_month_usd: string;
  /** ISO date (YYYY-MM-DD) of the current day-bucket, or null when the
   *  budget row has never been charged. */
  day_bucket: string | null;
  /** YYYY-MM string of the current month-bucket, or null. */
  month_bucket: string | null;
}

export interface OrgAiCostBudgetUpdatePayload {
  daily_cap_usd?: string | number;
  monthly_cap_usd?: string | number;
}

@Injectable({ providedIn: 'root' })
export class AiProvidersApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/ai`;

  // --- Provider keys ---------------------------------------------------

  list(): Observable<AiProviderKey[]> {
    return this.http.get<AiProviderKey[]>(`${this.base}/providers`);
  }

  create(payload: AiProviderKeyCreatePayload): Observable<AiProviderKey> {
    return this.http.post<AiProviderKey>(`${this.base}/providers`, payload);
  }

  test(keyId: string): Observable<AiProviderKey> {
    return this.http.post<AiProviderKey>(`${this.base}/providers/${keyId}/test`, {});
  }

  delete(keyId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/providers/${keyId}`);
  }

  reassign(payload: AiProviderKeyReassignPayload): Observable<{ reassigned_count: number }> {
    return this.http.post<{ reassigned_count: number }>(`${this.base}/providers/reassign`, payload);
  }

  // --- Budget ----------------------------------------------------------

  getBudget(): Observable<OrgAiCostBudget> {
    return this.http.get<OrgAiCostBudget>(`${this.base}/budget`);
  }

  updateBudget(payload: OrgAiCostBudgetUpdatePayload): Observable<OrgAiCostBudget> {
    return this.http.patch<OrgAiCostBudget>(`${this.base}/budget`, payload);
  }
}
