import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, finalize, shareReplay, tap } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from './token-storage.service';

export interface LoginRequest {
  email: string;
  password: string;
  org_slug?: string | null;
  two_factor_code?: string | null;
  two_factor_method?: 'authenticator' | 'email' | 'sms' | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

/** Discriminated response when the user has 2FA enabled and no code
 * was submitted with the first POST. The OTP (for email/sms) has
 * already been dispatched; the UI navigates to `/accounts/two-factor`
 * and re-POSTs `/auth/login` with the code. */
export interface TwoFactorChallengeResponse {
  requires_two_factor: true;
  method: 'authenticator' | 'email' | 'sms';
  available_methods: ('authenticator' | 'email' | 'sms')[];
}

export type LoginOutcome = LoginResponse | TwoFactorChallengeResponse;

export function isTwoFactorChallenge(res: LoginOutcome): res is TwoFactorChallengeResponse {
  return (res as TwoFactorChallengeResponse).requires_two_factor === true;
}

/** Body accepted by `POST /api/v1/auth/2fa/try-another-way` (layered
 *  user path — the backend also accepts the legacy admin envelope). */
export interface TryAnotherWayRequest {
  email: string;
  password: string;
  method: 'authenticator' | 'email' | 'sms';
  org_slug?: string | null;
}

export interface TryAnotherWayResponse {
  method: string;
  available_methods: string[];
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone?: string | null;
}

export interface RegisterResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  organization_id: string;
  organization_slug: string;
  role_name: string;
  /** `true` for self-signup — the org is in `template_id="pending"`
   * state and the user must finish onboarding before reaching
   * `/user`. */
  needs_onboarding: boolean;
}

export interface OrgSummary {
  id: string;
  name: string;
  slug: string;
  template_id: string;
  /** Org-level default currency (3-letter ISO). Money-formatting UIs
   * (lead detail, invoices) fall back to this when the row itself
   * doesn't carry a per-record currency. Backend defaults to 'INR'. */
  currency: string;
}

export interface MeResponse {
  id: string;
  org_id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  role_name: string;
  permission_keys: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  org: OrgSummary;
  /** Derived server-side from `org.template_id === "pending"`. Step
   * 4's route guard reads this to redirect users with unfinished
   * onboarding back to `/onboarding`. */
  needs_onboarding: boolean;
}

export interface OnboardingCompleteRequest {
  organization_name: string;
  template_id: string;
  country?: string | null;
  currency?: string | null;
  team_size?: string | null;
}

export interface OnboardingCompleteResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  organization_id: string;
  organization_slug: string;
  role_name: string;
  needs_onboarding: boolean;
  /** Non-fatal errors emitted by the pack installer during onboarding.
   *  Backend still returns 200 (org IS onboarded), but individual
   *  sections (pipelines / custom fields / lead sources / call
   *  outcomes) may have partially failed. Frontend surfaces these as a
   *  warning snackbar so the user knows to re-run `install_pack` from
   *  Settings if something is missing. Empty on a clean install. */
  install_warnings: string[];
}

@Injectable({ providedIn: 'root' })
export class FurnitureAuthService {
  private readonly http = inject(HttpClient);
  private readonly storage = inject(TokenStorageService);

  /** The current tenant's identity, populated on every `/me` fetch.
   * Components (sidebar header, breadcrumbs, etc.) bind to this to
   * brand the shell. Null before the first /me lands (login splash). */
  readonly currentOrg = signal<OrgSummary | null>(null);

  /** Permission keys for the signed-in user. Empty until the first
   * `/me` lands. Consumers (kanban admin affordances, etc.) read this
   * to decide whether to render management UI. */
  readonly currentPermissions = signal<string[]>([]);

  /** Display name of the signed-in user's active role ("Owner",
   * "Admin", "Employee", "Sales Manager", …). Empty before first /me. */
  readonly currentRoleName = signal<string>('');

  /** Signed-in user's UUID (matches `assigned_to_id` shape on contacts /
   * leads / walk-ins / appointments / tasks). Drives the "My contacts"
   * / "Mine" preset on list filters. Null before first /me. */
  readonly currentUserId = signal<string | null>(null);

  /** `true` once a `/users/me` response has been bound to the signals
   * above. The no-org route guard reads this to know whether it can
   * trust `needsOnboarding()` or has to fetch first. */
  readonly userLoaded = signal<boolean>(false);

  /** Mirror of `MeResponse.needs_onboarding` — true while the user's
   * org is still in `template_id="pending"` (self-signup not yet
   * finished on `/onboarding`). The no-org route guard reads this on every
   * `/user/**` navigation to redirect back to `/onboarding`. */
  readonly needsOnboarding = signal<boolean>(false);

  hasPermission(key: string): boolean {
    return this.currentPermissions().includes(key);
  }

  login(
    email: string,
    password: string,
    orgSlug?: string | null,
    twoFactorCode?: string | null,
    twoFactorMethod?: 'authenticator' | 'email' | 'sms' | null,
  ): Observable<LoginOutcome> {
    const body: LoginRequest = { email, password };
    if (orgSlug) body.org_slug = orgSlug;
    if (twoFactorCode) body.two_factor_code = twoFactorCode;
    if (twoFactorMethod) body.two_factor_method = twoFactorMethod;
    return this.http.post<LoginOutcome>(`${environment.apiBaseUrl}/auth/login`, body).pipe(
      tap((res) => {
        // Only persist the token on a real LoginResponse. A 2FA
        // challenge carries no `access_token` — attempting to store
        // it would silently overwrite any existing token with
        // `undefined` and 401 the app on the next request.
        if (!isTwoFactorChallenge(res)) {
          this.storage.setTokens(res.access_token, res.access_token);
        }
      }),
    );
  }

  /** Switch to a different 2FA method (email/sms/authenticator) mid-login.
   *  Backend re-verifies the password, so the login page passes the
   *  identifier + password it captured on the first submit. */
  tryAnotherWay(req: TryAnotherWayRequest): Observable<TryAnotherWayResponse> {
    return this.http.post<TryAnotherWayResponse>(
      `${environment.apiBaseUrl}/auth/2fa/try-another-way`,
      req,
    );
  }

  register(req: RegisterRequest): Observable<RegisterResponse> {
    return this.http
      .post<RegisterResponse>(`${environment.apiBaseUrl}/auth/register`, req)
      .pipe(tap((res) => this.storage.setTokens(res.access_token, res.access_token)));
  }

  completeOnboarding(req: OnboardingCompleteRequest): Observable<OnboardingCompleteResponse> {
    return this.http
      .post<OnboardingCompleteResponse>(`${environment.apiBaseUrl}/auth/onboarding/complete`, req)
      .pipe(
        // Backend rotates the JWT and revokes the previous session, so
        // we MUST replace the stored token with the new one — otherwise
        // the next request goes out under a revoked session and 401s.
        tap((res) => this.storage.setTokens(res.access_token, res.access_token)),
      );
  }

  /** Dedup guard: while a refresh is in flight, every 401 that lands
   *  reuses the SAME Observable. Prevents the multi-tab / parallel-
   *  request race where two 401s each trigger their own POST /refresh
   *  and end up racing to overwrite localStorage. Cleared on complete
   *  or error so the next real 401 kicks off a fresh refresh. */
  private refreshInFlight: Observable<LoginResponse> | null = null;

  refresh(): Observable<LoginResponse> {
    if (this.refreshInFlight) {
      return this.refreshInFlight;
    }
    this.refreshInFlight = this.http
      .post<LoginResponse>(`${environment.apiBaseUrl}/auth/refresh`, {})
      .pipe(
        tap((res) => this.storage.setTokens(res.access_token, res.access_token)),
        finalize(() => {
          this.refreshInFlight = null;
        }),
        // `shareReplay({ bufferSize: 1, refCount: false })` so every
        // late subscriber (parallel 401 arriving after the response)
        // still gets the cached new token instead of firing a second
        // POST.
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    return this.refreshInFlight;
  }

  logout(): Observable<void> {
    return this.http.post<void>(`${environment.apiBaseUrl}/auth/logout`, {}).pipe(
      tap(() => {
        this.storage.clear();
        this.currentOrg.set(null);
        this.currentPermissions.set([]);
        this.currentUserId.set(null);
        this.userLoaded.set(false);
        this.needsOnboarding.set(false);
      }),
    );
  }

  me(): Observable<MeResponse> {
    return this.http.get<MeResponse>(`${environment.apiBaseUrl}/users/me`).pipe(
      tap((res) => {
        this.currentOrg.set(res.org);
        this.currentPermissions.set(res.permission_keys);
        this.currentRoleName.set(res.role_name);
        this.currentUserId.set(res.id);
        this.needsOnboarding.set(res.needs_onboarding);
        this.userLoaded.set(true);
      }),
    );
  }

  isAuthenticated(): boolean {
    return this.storage.getAccess() !== null;
  }

  clearSession(): void {
    this.storage.clear();
    this.currentOrg.set(null);
    this.currentPermissions.set([]);
    this.currentRoleName.set('');
    this.currentUserId.set(null);
    this.userLoaded.set(false);
    this.needsOnboarding.set(false);
  }
}
