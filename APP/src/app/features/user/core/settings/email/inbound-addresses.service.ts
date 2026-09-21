/**
 * Inbound-addresses API service (tasks/email-inbound-forwarding Step 5).
 *
 * Thin ``HttpClient`` wrapper over the shipped forwarded-address
 * endpoints on ``/api/v1/channel-endpoints``:
 *
 *   * ``GET  /channel-endpoints?endpoint_type=forwarded_address``
 *   * ``POST /channel-endpoints/forwarded-address``
 *   * ``PATCH /channel-endpoints/forwarded-address/{id}``
 *   * ``POST /channel-endpoints/{id}/deactivate``
 *   * ``DELETE /channel-endpoints/forwarded-address/{id}``
 *
 * The listing endpoint returns the generic ``ChannelEndpointOut``
 * shape; this service adapts it into the tab-facing
 * ``ForwardedAddress`` type by composing the ``forwarding_address``
 * string from ``inbound-domain`` + the details row's forwarding_token
 * — wait, no. The token is never returned by the backend. The tab
 * calls ``POST /forwarded-address`` for creation which DOES return
 * the composed address; for the list view we rely on the backend's
 * companion ``ForwardedAddressOut`` shape, which the ``GET /channel-
 * endpoints`` list endpoint already flattens details onto. See the
 * ``list()`` implementation for the compose step.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import type {
  CreateForwardedAddressRequest,
  ForwardedAddress,
  UpdateForwardedAddressRequest,
} from './models';

@Injectable({ providedIn: 'root' })
export class InboundAddressesService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/channel-endpoints`;

  /** ``GET /channel-endpoints/forwarded-address`` — every active
   * forwarded-address endpoint for the caller's org, with the
   * composed ``f-<token>@<inbound-domain>`` address included. */
  list(): Observable<ForwardedAddress[]> {
    return this.http.get<ForwardedAddress[]>(`${this.base}/forwarded-address`);
  }

  /** ``POST /channel-endpoints/forwarded-address``. Returns the
   * ``ForwardedAddress`` shape directly — the response DOES include
   * the composed ``forwarding_address`` string because the create
   * flow is where the operator sees it for the first time. */
  create(payload: CreateForwardedAddressRequest): Observable<ForwardedAddress> {
    return this.http.post<ForwardedAddress>(`${this.base}/forwarded-address`, payload);
  }

  /** ``PATCH /channel-endpoints/forwarded-address/{id}``. Every field
   * on ``UpdateForwardedAddressRequest`` is optional — the row-inline
   * toggles PATCH one attribute at a time. */
  update(id: string, payload: UpdateForwardedAddressRequest): Observable<ForwardedAddress> {
    return this.http.patch<ForwardedAddress>(`${this.base}/forwarded-address/${id}`, payload);
  }

  /** ``POST /channel-endpoints/{id}/deactivate``. Idempotent — a
   * second call on an already-inactive row returns 204 with no
   * side-effects. */
  deactivate(id: string, reason?: string): Observable<void> {
    return this.http.post<void>(`${this.base}/${id}/deactivate`, reason ? { reason } : {});
  }

  /** ``DELETE /channel-endpoints/forwarded-address/{id}``. Hard-
   * delete — the endpoint + its details row are removed. Historical
   * messages stay intact (their ``payload.endpoint_id`` is a string,
   * not an FK). */
  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/forwarded-address/${id}`);
  }
}
