import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { ITokenPayload, IUserDetails } from '@app/schemas/common';
import { STORAGE_KEY_TOKEN, STORAGE_KEY_ADMIN_IMPERSONATION, ROLE_USER, ROLE_ADMIN } from '@core/constants/app.constants';
import { getRoute } from '@core/services/routes-helper.service';
import { AuthApiService } from '@app/services/auth-api.service';
import { PushNotificationService } from '@core/services/push-notification.service';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly router = inject(Router);
  private readonly authApi = inject(AuthApiService);
  private readonly pushNotification = inject(PushNotificationService);

  getToken(): string | null {
    return sessionStorage.getItem(STORAGE_KEY_TOKEN) ?? localStorage.getItem(STORAGE_KEY_TOKEN);
  }

  setToken(token: string, remember: boolean): void {
    if (remember) {
      localStorage.setItem(STORAGE_KEY_TOKEN, token);
      sessionStorage.removeItem(STORAGE_KEY_TOKEN);
    } else {
      sessionStorage.setItem(STORAGE_KEY_TOKEN, token);
      localStorage.removeItem(STORAGE_KEY_TOKEN);
    }
  }

  isLoggedIn(): boolean {
    const token = this.getToken();
    if (!token) return false;
    const payload = this.decodeToken(token);
    if (!payload) return false;
    return payload.exp * 1000 > Date.now();
  }

  isUser(): boolean {
    return this.getUserDetails()?.role === ROLE_USER;
  }

  isAdmin(): boolean {
    return this.getUserDetails()?.role === ROLE_ADMIN;
  }

  getUserDetails(): IUserDetails | null {
    const token = this.getToken();
    if (!token) return null;
    const payload = this.decodeToken(token);
    if (!payload) return null;

    const accessRights = payload.access_rights
      ? payload.access_rights.split(',').map(Number).filter((n) => !isNaN(n))
      : [];

    return {
      tokenId: payload.token_id,
      userId: payload.user_id,
      role: payload.role,
      accessRights,
      isSuperAdmin: payload.is_super_admin ?? false,
    };
  }

  startImpersonation(userToken: string): void {
    const adminToken = this.getToken();
    if (adminToken) {
      sessionStorage.setItem(STORAGE_KEY_ADMIN_IMPERSONATION, adminToken);
    }
    sessionStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    sessionStorage.setItem(STORAGE_KEY_TOKEN, userToken);
  }

  isImpersonating(): boolean {
    return !!sessionStorage.getItem(STORAGE_KEY_ADMIN_IMPERSONATION);
  }

  async stopImpersonation(): Promise<void> {
    try {
      await this.authApi.logout();
    } catch {
      // Best-effort
    }

    const adminToken = sessionStorage.getItem(STORAGE_KEY_ADMIN_IMPERSONATION);
    sessionStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    sessionStorage.removeItem(STORAGE_KEY_ADMIN_IMPERSONATION);

    if (adminToken) {
      sessionStorage.setItem(STORAGE_KEY_TOKEN, adminToken);
    }

    this.router.navigate([getRoute('admin_dashboard').url]);
  }

  async logout(): Promise<void> {
    if (this.isImpersonating()) {
      await this.stopImpersonation();
      return;
    }
    const wasAdmin = this.isAdmin();
    try {
      await this.pushNotification.unregisterCurrentToken();
    } catch {
      // Best-effort — unregister failure must not prevent logout
    }
    try {
      await this.authApi.logout();
    } catch {
      // Best-effort — continue with local logout even if API call fails
    }
    sessionStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    sessionStorage.removeItem('popup_shown');
    const loginUrl = wasAdmin ? getRoute('admin_login').url : getRoute('login').url;
    this.router.navigate([loginUrl]);
  }

  private decodeToken(token: string): ITokenPayload | null {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const payload = JSON.parse(atob(parts[1]));
      return payload as ITokenPayload;
    } catch {
      return null;
    }
  }
}
