/**
 * Reputation dashboard API service
 * (tasks/email-reputation-warmup Step 7).
 *
 * Thin ``HttpClient`` wrapper over the single backend endpoint:
 *
 *   * ``GET /api/v1/reputation/dashboard``
 *
 * The GET is naturally retried by the app-wide HTTP retry
 * interceptor on transient failures (see memory
 * ``feedback_http_retry_interceptor``). The component auto-refreshes
 * every 30 s while the tab is visible so counter bumps land without
 * a manual reload.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type ReputationState = 'ok' | 'warned' | 'blocked';
export type EnvelopeType = 'platform_from' | 'own_domain';

/** One row on the dashboard — matches
 * ``api/src/app/core/email/reputation/schemas.py:EnvelopeReputationOut``. */
export interface EnvelopeReputation {
  envelope_type: EnvelopeType;
  domain_id: string | null;
  domain_string: string | null;
  warmup_stage: number;
  stage_cap: number;
  next_stage_cap: number;
  stage_progress_pct: number;
  daily_sent: number;
  daily_cap: number;
  delivered_24h: number;
  bounced_24h: number;
  complained_24h: number;
  unsubscribed_24h: number;
  complaint_rate: number;
  bounce_rate: number;
  reputation_state: ReputationState;
  blocked_until: string | null;
}

@Injectable({ providedIn: 'root' })
export class ReputationService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/reputation`;

  /** ``GET /api/v1/reputation/dashboard`` — one row per envelope.
   * 403 for non-Owner. Empty list only happens for a brand-new org
   * with zero verified domains AND the platform-from row would be
   * synthesised server-side; empty here means the backend didn't
   * seed the pristine row (regression). */
  list(): Observable<EnvelopeReputation[]> {
    return this.http.get<EnvelopeReputation[]>(`${this.base}/dashboard`);
  }
}
