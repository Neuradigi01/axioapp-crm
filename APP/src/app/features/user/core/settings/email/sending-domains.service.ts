/**
 * Sending Domains API service (tasks/email-sending-domains Step 7).
 *
 * Thin ``HttpClient`` wrapper over the four backend endpoints:
 *
 *   * ``GET    /api/v1/sender-domains``
 *   * ``POST   /api/v1/sender-domains``
 *   * ``POST   /api/v1/sender-domains/{id}/verify``
 *   * ``DELETE /api/v1/sender-domains/{id}``
 *
 * The GET is naturally retried by the app-wide HTTP retry interceptor
 * on transient failures (see memory ``feedback_http_retry_interceptor``).
 * Mutations (``POST`` / ``DELETE``) are single-shot — no accidental
 * double-claim on a network wobble.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import type { ClaimDomainRequest, SendingDomain } from './models';

@Injectable({ providedIn: 'root' })
export class SendingDomainsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/sender-domains`;

  /** ``GET /api/v1/sender-domains`` — every domain the org has ever
   * claimed, newest first. Released rows are included so the frontend
   * can render the historical timeline. */
  list(): Observable<SendingDomain[]> {
    return this.http.get<SendingDomain[]>(this.base);
  }

  /** ``POST /api/v1/sender-domains`` — claim a new domain. Returns the
   * pending row with Mailgun's verbatim ``dns_records`` blob. 409 on
   * global-uniqueness conflict; 422 on invalid shape. */
  claim(payload: ClaimDomainRequest): Observable<SendingDomain> {
    return this.http.post<SendingDomain>(this.base, payload);
  }

  /** ``POST /api/v1/sender-domains/{id}/verify`` — force a fresh
   * Mailgun verify + return the updated row. Cross-org / missing id
   * → 404. 502 when Mailgun is temporarily unavailable. */
  verify(id: string): Observable<SendingDomain> {
    return this.http.post<SendingDomain>(`${this.base}/${id}/verify`, {});
  }

  /** ``DELETE /api/v1/sender-domains/{id}`` — release + cascade. 204
   * on success. Idempotent w.r.t. Mailgun's own state (a Mailgun 404
   * is treated as success by the API client wrapper). */
  release(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
