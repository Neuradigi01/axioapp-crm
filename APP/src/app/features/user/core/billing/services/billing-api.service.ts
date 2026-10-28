import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import {
  CheckoutRequest,
  CheckoutResponse,
  Invoice,
  PlansResponse,
  SeatChangeResponse,
  SeatPreview,
  SubscriptionCurrent,
} from '../types/subscription.types';

/**
 * Thin wrapper over the authenticated billing endpoints.
 *
 * Step 15 only consumes `GET /subscriptions/current`. Steps 16 / 17 /
 * 20 will add `change`, `cancel`, `seats`, `checkout`, and the
 * invoice list — all live on this service so the HTTP interceptors
 * (auth, retry) apply uniformly.
 */
@Injectable({ providedIn: 'root' })
export class BillingApiService {
  private readonly http = inject(HttpClient);

  getCurrent(): Observable<SubscriptionCurrent> {
    return this.http.get<SubscriptionCurrent>(`${environment.apiBaseUrl}/subscriptions/current`);
  }

  /** Step 13.c — Stripe-mirrored invoice list, newest first. Empty
   *  array during trial (no Stripe activity yet). */
  listInvoices(): Observable<Invoice[]> {
    return this.http.get<Invoice[]>(`${environment.apiBaseUrl}/subscriptions/invoices`);
  }

  /** Step 14 — public plan catalogue. Used by the upgrade modal
   *  (Step 17) to render the radio cards. Unauthenticated on the
   *  server side; the auth interceptor still attaches the JWT but
   *  the endpoint ignores it. */
  getPlans(): Observable<PlansResponse> {
    return this.http.get<PlansResponse>(`${environment.apiBaseUrl}/plans`);
  }

  /** Step 12 — request a Stripe Checkout Session for an upgrade.
   *  Returns the hosted URL the frontend redirects into via
   *  `window.location.href`. */
  createCheckoutSession(payload: CheckoutRequest): Observable<CheckoutResponse> {
    return this.http.post<CheckoutResponse>(
      `${environment.apiBaseUrl}/subscriptions/checkout`,
      payload,
    );
  }

  /** Step 9 — preview the cost impact of a seat change without
   *  committing. The seat-management modal calls this on every
   *  +/− click so the displayed estimate stays in sync. */
  previewSeats(totalSeats: number): Observable<SeatPreview> {
    return this.http.get<SeatPreview>(`${environment.apiBaseUrl}/subscriptions/seats/preview`, {
      params: { total_seats: totalSeats },
    });
  }

  /** Step 9 — apply or schedule a seat change. The response shape is
   *  a discriminated union; the modal switches on `outcome`. */
  changeSeats(totalSeats: number): Observable<SeatChangeResponse> {
    return this.http.post<SeatChangeResponse>(`${environment.apiBaseUrl}/subscriptions/seats`, {
      total_seats: totalSeats,
    });
  }
}
