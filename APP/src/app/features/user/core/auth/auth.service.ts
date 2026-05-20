import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from './token-storage.service';

export interface LoginRequest {
  email: string;
  password: string;
  org_slug?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone?: string | null;
  organization_name?: string | null;
}

export interface RegisterResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  organization_id: string;
  organization_slug: string;
  role_name: string;
}

export interface OrgSummary {
  id: string;
  name: string;
  slug: string;
  pack_id: string;
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

  hasPermission(key: string): boolean {
    return this.currentPermissions().includes(key);
  }

  login(email: string, password: string, orgSlug?: string | null): Observable<LoginResponse> {
    const body: LoginRequest = { email, password };
    if (orgSlug) body.org_slug = orgSlug;
    return this.http
      .post<LoginResponse>(`${environment.apiBaseUrl}/auth/login`, body)
      .pipe(
        tap((res) => this.storage.setTokens(res.access_token, res.access_token)),
      );
  }

  register(req: RegisterRequest): Observable<RegisterResponse> {
    return this.http
      .post<RegisterResponse>(`${environment.apiBaseUrl}/auth/register`, req)
      .pipe(
        tap((res) => this.storage.setTokens(res.access_token, res.access_token)),
      );
  }

  refresh(): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${environment.apiBaseUrl}/auth/refresh`, {})
      .pipe(
        tap((res) => this.storage.setTokens(res.access_token, res.access_token)),
      );
  }

  logout(): Observable<void> {
    return this.http
      .post<void>(`${environment.apiBaseUrl}/auth/logout`, {})
      .pipe(
        tap(() => {
          this.storage.clear();
          this.currentOrg.set(null);
          this.currentPermissions.set([]);
        }),
      );
  }

  me(): Observable<MeResponse> {
    return this.http
      .get<MeResponse>(`${environment.apiBaseUrl}/users/me`)
      .pipe(
        tap((res) => {
          this.currentOrg.set(res.org);
          this.currentPermissions.set(res.permission_keys);
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
  }
}
