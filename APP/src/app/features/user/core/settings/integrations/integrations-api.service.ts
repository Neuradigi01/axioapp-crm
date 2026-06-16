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
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../shared/services/query-builder';


// --- Shared shapes (mirror backend `core/integrations/schemas.py`) ----


export type IntegrationProvider = 'google_ads' | 'meta_ads' | 'whatsapp';

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


// --- Step 8: dashboard + mapping editor shapes ------------------------


/** One row in `GET /api/v1/leads/import/targets` — reused as the CRM
 *  target dropdown options in the field-mapping editor (Step 8) and
 *  the bulk-import column mapper. Schema mirrors backend
 *  `core.leads.imports.schemas.MappingTarget`. */
export interface MappingTarget {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  custom: boolean;
}


export interface ProviderDeliveryStatus {
  provider: IntegrationProvider;
  status: IntegrationStatus;
  last_delivery_at: string | null;
  deliveries_24h_accepted: number;
  deliveries_24h_failed: number;
}


export interface IntegrationStatusResponse {
  providers: ProviderDeliveryStatus[];
  /** Count of DLQ rows NOT yet replayed or discarded. Drives the
   *  panel's "X failed deliveries need attention" banner. */
  dlq_open_total: number;
}


// --- WhatsApp Business Account (Step 3.5.1+) -------------------------


/** Projection returned by every WA endpoint that reports lifecycle
 *  state. Mirrors backend `WhatsAppStatusOut`. The Settings card uses
 *  the same shape for the initial `GET /status` fetch and for every
 *  subsequent action response — single render path keeps the UI tidy. */
export interface WhatsAppStatus {
  status: IntegrationStatus;
  phone_id: string | null;
  waba_id: string | null;
  display_phone_number: string | null;
  verified_name: string | null;
  api_version: string | null;
  rate_limit_per_sec: number | null;
  last_error: string | null;
  connected_at: string | null;
}


/** HTTP body for `POST /api/v1/integrations/whatsapp/connect`.
 *  All 5 base fields are required; `api_version` defaults to `v18.0`
 *  on the backend if omitted. Mirrors backend `WhatsAppConnectIn`. */
export interface WhatsAppConnectPayload {
  phone_id: string;
  waba_id: string;
  access_token: string;
  app_secret: string;
  verify_token: string;
  api_version?: string;
  /** Step 3.5.15 — per-org outbound rate cap (msg/sec). 1..1000. */
  rate_limit_per_sec?: number;
}


export interface WhatsAppTemplate {
  id: string;
  name: string;
  language: string;
  category: string;
  status: string;
  body: string;
  header_type: string | null;
  header_text: string | null;
  footer_text: string | null;
  variable_count: number;
  meta_template_id: string | null;
  last_synced_at: string;
}


export interface WhatsAppTemplateSyncResult {
  added: number;
  updated: number;
  removed: number;
  total: number;
}


/** Response shape from `GET /api/v1/integrations/whatsapp/capacity` —
 *  drives the campaign create modal's quota banner (Step 3.5.16).
 *  Mirrors backend `WhatsAppCapacityOut`.
 *
 *  `daily_limit` and `remaining` are both `-1` when `is_unlimited`
 *  is true; the UI uses those sentinels to hide the progress bar
 *  and the "X remaining" copy. `usage_percent` is capped at 100. */
export interface WhatsAppCapacity {
  tier: string;
  tier_label: string;
  daily_limit: number;
  used_today: number;
  remaining: number;
  usage_percent: number;
  is_unlimited: boolean;
}


export interface DlqListFilters {
  page?: number;
  size?: number;
  provider?: IntegrationProvider;
  /** Default true on the backend. Pass `false` to get only un-
   *  addressed failures (drives the dashboard's open-failures view). */
  include_replayed?: boolean;
}


@Injectable({ providedIn: 'root' })
export class IntegrationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations`;
  /** Bulk-import mapping-target endpoint is on `/leads/import`,
   *  not under `/integrations` — but the field-mapping editor reuses
   *  it verbatim, so we keep the dependency in one place. */
  private readonly leadsImportBase = `${environment.apiBaseUrl}/leads/import`;

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
      ? buildHttpParams({ integration_id: integrationId })
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

  // --- DLQ (Step 3 list + Step 8 filters/discard/replay) ---------

  /** Paginated DLQ list. Step 8 adds provider + include_replayed
   *  filters so the dashboard can show "open failures only" while
   *  Step 7's summary card just needs the unfiltered total. */
  listDlq(filters: DlqListFilters = {}): Observable<IntegrationDLQListResponse> {
    const params = buildHttpParams({
      page: filters.page ?? 1,
      size: filters.size ?? 50,
      provider: filters.provider,
      include_replayed:
        filters.include_replayed === false ? false : undefined,
    });
    return this.http.get<IntegrationDLQListResponse>(`${this.base}/dlq`, {
      params,
    });
  }

  /** Re-enqueue a DLQ payload through the matching provider's
   *  Celery task. Row survives with `replayed_at` stamped. */
  replayDlq(dlqId: string): Observable<IntegrationDLQRow> {
    return this.http.post<IntegrationDLQRow>(
      `${this.base}/dlq/${dlqId}/replay`,
      {},
    );
  }

  /** Soft-discard a DLQ row — stamps `replayed_at` with
   *  `replayed_by=NULL` so the status panel + open-failures view
   *  exclude it. Row survives for forensic trail. */
  discardDlq(dlqId: string): Observable<IntegrationDLQRow> {
    return this.http.post<IntegrationDLQRow>(
      `${this.base}/dlq/${dlqId}/discard`,
      {},
    );
  }

  // --- Step 8: Status dashboard + mapping editor -------------------

  /** Per-provider delivery snapshot for the Settings dashboard.
   *  Polled every ~30s by the Status panel. */
  getStatus(): Observable<IntegrationStatusResponse> {
    return this.http.get<IntegrationStatusResponse>(`${this.base}/status`);
  }

  /** Replace a subscription's `field_mapping`. Empty mapping is
   *  allowed (means "drop everything" — webhook payloads will DLQ
   *  until restored). Backend validates target keys against
   *  `GET /leads/import/targets`. */
  updateSubscriptionMapping(
    subscriptionId: string,
    mapping: Record<string, string>,
  ): Observable<IntegrationSubscription> {
    return this.http.put<IntegrationSubscription>(
      `${this.base}/subscriptions/${subscriptionId}/mapping`,
      { mapping },
    );
  }

  /** Fetch the CRM target dropdown options. Reused from the bulk-
   *  import surface — same shape, same validation contract. */
  listMappingTargets(): Observable<MappingTarget[]> {
    return this.http.get<MappingTarget[]>(`${this.leadsImportBase}/targets`);
  }

  // --- WhatsApp Business Account (Step 3.5.1) ---------------------

  /** Current connection state for the active org's WhatsApp Business
   *  Account. Returns `{status:'disconnected'}` (200, not 404) when the
   *  org has never connected — keeps the Settings card render path
   *  uniform. NEVER includes `access_token` or `app_secret`. */
  getWhatsAppStatus(): Observable<WhatsAppStatus> {
    return this.http.get<WhatsAppStatus>(`${this.base}/whatsapp/status`);
  }

  /** Validate credentials with Meta's Graph API, then persist on
   *  success. Single-call connect-and-test — backend rejects with
   *  HTTP 400 if Meta refuses the token (response detail is Meta's
   *  error message verbatim, suitable for showing to the operator). */
  connectWhatsApp(payload: WhatsAppConnectPayload): Observable<WhatsAppStatus> {
    return this.http.post<WhatsAppStatus>(
      `${this.base}/whatsapp/connect`,
      payload,
    );
  }

  /** Re-ping Meta with stored credentials. Flips status to `error`
   *  with `last_error` populated on rejection; returns 400 in that
   *  case. Also 400 when the org has never connected. */
  testWhatsApp(): Observable<WhatsAppStatus> {
    return this.http.post<WhatsAppStatus>(
      `${this.base}/whatsapp/test`,
      {},
    );
  }

  /** Null the stored token + flip status to `disconnected`. Sidecar
   *  config (phone_id, waba_id) survives so reconnect can prefill. */
  disconnectWhatsApp(): Observable<void> {
    return this.http.post<void>(
      `${this.base}/whatsapp/disconnect`,
      {},
    );
  }

  // --- WhatsApp templates (Step 3.5.4 backend, 3.5.5 frontend) ----

  /** Pull approved templates from Meta into local cache. Returns
   *  counts the Settings UI shows in a toast: "3 added, 1 updated".
   *  409 if WA is not connected. */
  syncWhatsAppTemplates(): Observable<WhatsAppTemplateSyncResult> {
    return this.http.post<WhatsAppTemplateSyncResult>(
      `${this.base}/whatsapp/templates/sync`,
      {},
    );
  }

  /** List cached templates for the active org. The campaign create-
   *  modal picker calls this with `status=APPROVED` to show only
   *  Meta-approved templates. */
  listWhatsAppTemplates(filters?: {
    status?: string;
    category?: string;
  }): Observable<WhatsAppTemplate[]> {
    const params = buildHttpParams({
      status: filters?.status,
      category: filters?.category,
    });
    return this.http.get<WhatsAppTemplate[]>(
      `${this.base}/whatsapp/templates`,
      { params },
    );
  }

  // --- WhatsApp send capacity (Step 3.5.16) -----------------------

  /** Current Meta messaging tier + today's used quota. The campaign
   *  create modal renders this as a "X / Y remaining today" banner
   *  before sending. 409 when WhatsApp is not connected — the modal
   *  treats that as "hide the banner". */
  getWhatsAppCapacity(): Observable<WhatsAppCapacity> {
    return this.http.get<WhatsAppCapacity>(
      `${this.base}/whatsapp/capacity`,
    );
  }
}
