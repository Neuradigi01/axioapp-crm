import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from './token-storage.service';

export interface LoginRequest {
  email: string;
  password: string;
  org_slug: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
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
}

@Injectable({ providedIn: 'root' })
export class FurnitureAuthService {
  private readonly http = inject(HttpClient);
  private readonly storage = inject(TokenStorageService);

  login(email: string, password: string, orgSlug: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${environment.apiBaseUrl}/auth/login`, {
        email,
        password,
        org_slug: orgSlug,
      } satisfies LoginRequest)
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
      .pipe(tap(() => this.storage.clear()));
  }

  me(): Observable<MeResponse> {
    return this.http.get<MeResponse>(`${environment.apiBaseUrl}/users/me`);
  }

  isAuthenticated(): boolean {
    return this.storage.getAccess() !== null;
  }

  clearSession(): void {
    this.storage.clear();
  }
}
