/**
 * Typed HTTP wrappers for the ad-integrations admin surface.
 *
 * One service covers BOTH providers (Google + Meta) + the shared
 * subscriptions / DLQ endpoints. The Step-7 Settings UI doesn't
 * exercise webhook receivers or OAuth callbacks — those are
 * unauthenticated and called by Google/Meta/an admin's browser
 * after consent, NOT by this SPA's XHR.
 *
 * Auth: every call goes through `HttpClient`, which the global
 * `auth.interceptor` decorates with `Authorization: Bearer <jwt>`.
 * The `/authorize` endpoints (Google + Meta) return `{url}` JSON
 * instead of a 302 specifically so this XHR pattern works — a
 * top-level browser navigation to a JWT-gated 302 would 401 before
 * reaching the redirect.
 *
 * All endpoints are gated server-side by
 * `settings.integrations.manage`. The Settings page hides the tab
 * for users without that permission; the API still enforces it
 * (defence in depth — a curious user typing the URL directly hits
 * the same 403).
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';


// --- Shared shapes (mirror backend `core/integrations/schemas.py`) ----


export type IntegrationProvider = 'google_ads' | 'meta_ads';

export type IntegrationStatus =
  | 'connected'
  | 'disconnected'
  | 'expired'
  | 'error';


export interface Integration {
  id: string;
  org_id: string;
  provider: IntegrationProvider;
  account_id: string | null;
  account_label: string | null;
  token_expires_at: string | null;
  scopes: string[] | null;
  status: IntegrationStatus;
  last_error: string | null;
  connected_at: string | null;
  connected_by: string | null;
  disconnected_at: string | null;
  disconnected_by: string | null;
  updated_at: string;
  /** Per-tenant secret embedded in the Google webhook URL.
   *  Null for Meta (Meta uses a single env-level URL with no
   *  per-tenant component). */
  webhook_secret: string | null;
  /** Provider-aware computed URL. Google: per-tenant URL with
   *  embedded secret; Meta: single env-level URL when connected;
   *  None otherwise. The Settings UI shows this in the webhook-
   *  config panel with a copy button. */
  webhook_url: string | null;
}


export interface IntegrationSubscription {
  id: string;
  org_id: string;
  integration_id: string;
  external_form_id: string;
  external_form_label: string | null;
  field_mapping: Record<string, string>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}


export interface SubscriptionCreatePayload {
  integration_id: string;
  external_form_id: string;
  external_form_label: string | null;
  field_mapping?: Record<string, string>;
  enabled?: boolean;
}


export interface SubscriptionUpdatePayload {
  external_form_label?: string | null;
  field_mapping?: Record<string, string>;
  enabled?: boolean;
}


export interface GoogleAdsAccount {
  customer_id: string;
  resource_name: string;
}


export interface GoogleLeadForm {
  form_id: string;
  name: string | null;
  resource_name: string;
}


export interface MetaPage {
  page_id: string;
  name: string;
  category: string | null;
}


export interface MetaLeadForm {
  form_id: string;
  name: string;
  status: string;
}


export interface IntegrationDLQRow {
  id: string;
  org_id: string;
  integration_id: string | null;
  provider: IntegrationProvider;
  payload: Record<string, unknown>;
  error_message: string;
  retries_attempted: number;
  created_at: string;
  replayed_at: string | null;
  replayed_by: string | null;
}


export interface IntegrationDLQListResponse {
  items: IntegrationDLQRow[];
  total: number;
  page: number;
  size: number;
}


/** Response shape from `GET /authorize` (Google + Meta) — JSON
 *  instead of 302 so the SPA's XHR can read the consent URL and
 *  then navigate the browser to it. */
export interface AuthorizeUrlResponse {
  url: string;
}


@Injectable({ providedIn: 'root' })
export class IntegrationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations`;

  // --- Generic management (Step 1) ---------------------------------

  /** List every connected/disconnected integration in the active
   *  org. Step-1 generic endpoint covers both providers. */
  list(): Observable<Integration[]> {
    return this.http.get<Integration[]>(this.base);
  }

  /** Disconnect a provider — clears tokens, status flips to
   *  `disconnected`, webhook_secret nulled. Idempotent: re-calling
   *  is a no-op 204. 404 if never connected. */
  disconnect(provider: IntegrationProvider): Observable<void> {
    return this.http.delete<void>(`${this.base}/${provider}`);
  }

  /** Mint a fresh webhook secret (Google only — Meta has no per-
   *  tenant secret). Old URL stops authenticating immediately. */
  rotateWebhookSecret(provider: IntegrationProvider): Observable<Integration> {
    return this.http.post<Integration>(
      `${this.base}/${provider}/webhook/rotate`,
      {},
    );
  }

  // --- Google Ads OAuth + discovery (Step 2) ----------------------

  /** Returns `{url}` — the Google consent URL the SPA should
   *  navigate the browser to via `window.location.assign(...)`. */
  startGoogleAuthorize(): Observable<AuthorizeUrlResponse> {
    return this.http.get<AuthorizeUrlResponse>(
      `${this.base}/google/authorize`,
    );
  }

  /** List Google Ads customers the connected OAuth user can see.
   *  Returns `[]` (not 404) when Google isn't connected — keeps
   *  the picker UI simple. */
  listGoogleAccounts(): Observable<GoogleAdsAccount[]> {
    return this.http.get<GoogleAdsAccount[]>(`${this.base}/google/accounts`);
  }

  /** Lead Forms on a Google Ads customer. `customer_id` may include
   *  hyphens (e.g. "123-456-7890"); the backend strips them. */
  listGoogleForms(customerId: string): Observable<GoogleLeadForm[]> {
    return this.http.get<GoogleLeadForm[]>(
      `${this.base}/google/accounts/${customerId}/forms`,
    );
  }

  // --- Meta OAuth + discovery (Step 4) ----------------------------

  startMetaAuthorize(): Observable<AuthorizeUrlResponse> {
    return this.http.get<AuthorizeUrlResponse>(
      `${this.base}/meta/authorize`,
    );
  }

  /** List Facebook Pages the OAuth user manages. Page tokens are
   *  NEVER returned (they're as sensitive as the user token; the
   *  backend re-fetches per request internally). */
  listMetaPages(): Observable<MetaPage[]> {
    return this.http.get<MetaPage[]>(`${this.base}/meta/pages`);
  }

  listMetaForms(pageId: string): Observable<MetaLeadForm[]> {
    return this.http.get<MetaLeadForm[]>(
      `${this.base}/meta/pages/${pageId}/forms`,
    );
  }

  /** Subscribe to the `leadgen` field on this Page. Backend
   *  caches the Page token so the webhook worker can fetch lead
   *  details without re-OAuthing. */
  subscribeMetaPage(pageId: string): Observable<{ status: string; page_id: string }> {
    return this.http.post<{ status: string; page_id: string }>(
      `${this.base}/meta/pages/${pageId}/subscribe`,
      {},
    );
  }

  unsubscribeMetaPage(pageId: string): Observable<{ status: string; page_id: string }> {
    return this.http.post<{ status: string; page_id: string }>(
      `${this.base}/meta/pages/${pageId}/unsubscribe`,
      {},
    );
  }

  // --- Subscriptions CRUD (Step 3) --------------------------------

  /** Form subscriptions in the active org, optionally filtered to
   *  one integration. The Settings cards filter client-side. */
  listSubscriptions(integrationId?: string): Observable<IntegrationSubscription[]> {
    const params = integrationId
      ? new HttpParams().set('integration_id', integrationId)
      : undefined;
    return this.http.get<IntegrationSubscription[]>(
      `${this.base}/subscriptions`,
      { params },
    );
  }

  createSubscription(
    payload: SubscriptionCreatePayload,
  ): Observable<IntegrationSubscription> {
    return this.http.post<IntegrationSubscription>(
      `${this.base}/subscriptions`,
      payload,
    );
  }

  updateSubscription(
    subscriptionId: string,
    payload: SubscriptionUpdatePayload,
  ): Observable<IntegrationSubscription> {
    return this.http.patch<IntegrationSubscription>(
      `${this.base}/subscriptions/${subscriptionId}`,
      payload,
    );
  }

  deleteSubscription(subscriptionId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.base}/subscriptions/${subscriptionId}`,
    );
  }

  // --- DLQ (Step 3 — list + count for this page; full UI in Step 8)

  /** Paginated DLQ list. Step 7 only needs the `total` for the
   *  bottom summary card; the full table lives in Step 8. */
  listDlq(page = 1, size = 1): Observable<IntegrationDLQListResponse> {
    const params = new HttpParams()
      .set('page', String(page))
      .set('size', String(size));
    return this.http.get<IntegrationDLQListResponse>(`${this.base}/dlq`, {
      params,
    });
  }
}
