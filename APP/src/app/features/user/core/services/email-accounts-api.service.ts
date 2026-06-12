/**
 * Typed HTTP wrappers for the email-accounts surface.
 *
 * Four endpoints:
 *
 *  - `list()`              — `GET /api/v1/email/accounts`. Returns the
 *                            caller's own accounts; Owners and Admins
 *                            with `email.accounts.admin` see all org
 *                            accounts via the same call (backend
 *                            decides).
 *  - `authorizeGmail()`    — `GET /api/v1/email/gmail/authorize`. The
 *                            response is `{url: string}` — the SPA
 *                            navigates the top-level browser via
 *                            `window.location.assign(url)`.
 *  - `authorizeMicrosoft()`— `GET /api/v1/email/microsoft/authorize`.
 *                            Same shape and dispatch.
 *  - `disconnect(id)`      — `DELETE /api/v1/email/accounts/{id}`. 204
 *                            No Content; idempotent.
 *
 * Auth: every call goes through `HttpClient`, which the global
 * interceptors decorate with `Authorization: Bearer <jwt>` and a
 * retry policy on transient failures (`retryInterceptor`).
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

// `environment.apiBaseUrl` already carries the `/api/v1` prefix —
// append just the resource path below.


export type EmailAccountProvider = 'gmail' | 'microsoft';

export type EmailAccountSyncState =
  | 'pending'
  | 'backfilling'
  | 'live'
  | 'error'
  | 'disconnected';


export interface EmailAccount {
  id: string;
  org_id: string;
  user_id: string;
  provider: EmailAccountProvider;
  external_account_id: string;
  email_address: string;
  display_name: string | null;
  token_expires_at: string | null;
  scopes_granted: string[];
  sync_state: EmailAccountSyncState;
  last_sync_at: string | null;
  last_sync_error: string | null;
  daily_sent_count: number;
  daily_sent_reset_at: string;
  connected_at: string;
  disconnected_at: string | null;
  disconnected_by: string | null;
}


export interface AuthorizeResponse {
  url: string;
}


@Injectable({ providedIn: 'root' })
export class EmailAccountsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/email`;

  /** Visible accounts for the caller. Reps see only their own; Owner
   *  / Admin (holding `email.accounts.admin`) see every account in
   *  the org. The backend filters; the SPA just renders what comes
   *  back. */
  list(): Observable<EmailAccount[]> {
    return this.http.get<EmailAccount[]>(`${this.base}/accounts`);
  }

  /** Returns the Google OAuth consent URL. The SPA navigates to it
   *  via `window.location.assign` — a top-level browser GET to
   *  `/api/v1/...` doesn't carry the Bearer header, so a 302 from
   *  the API would fail. JSON wrap-and-navigate is the workaround. */
  authorizeGmail(): Observable<AuthorizeResponse> {
    return this.http.get<AuthorizeResponse>(
      `${this.base}/gmail/authorize`,
    );
  }

  /** Same shape as `authorizeGmail` for the Microsoft Graph consent
   *  URL. The backend rejects with 503 when MICROSOFT_CLIENT_ID isn't
   *  configured (dev default); the UI handles that as a disabled
   *  state. */
  authorizeMicrosoft(): Observable<AuthorizeResponse> {
    return this.http.get<AuthorizeResponse>(
      `${this.base}/microsoft/authorize`,
    );
  }

  /** Disconnect an account. Returns 204 No Content; the wrapper types
   *  it as `void`. A rep without `email.accounts.admin` can only
   *  disconnect their own accounts; the backend returns 403 otherwise. */
  disconnect(accountId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/accounts/${accountId}`);
  }
}
