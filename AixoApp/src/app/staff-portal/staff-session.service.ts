import { Injectable, signal } from '@angular/core';

/**
 * Token storage for the staff portal.
 *
 * Uses a dedicated `staff_access_token` localStorage key so the admin
 * app (`access_token`) and the staff portal can be logged in
 * simultaneously without clobbering each other. The expiry, user_id,
 * and org_id from the login response are stored alongside the token so
 * the guard can fast-reject expired tokens without decoding the JWT.
 */
const TOKEN_KEY = 'staff_access_token';
const EXPIRES_KEY = 'staff_access_expires_at';
const USER_ID_KEY = 'staff_user_id';
const ORG_ID_KEY = 'staff_org_id';
const FULL_NAME_KEY = 'staff_full_name';

@Injectable({ providedIn: 'root' })
export class StaffSessionService {
  // Surface reactive state for the shell + guards.
  readonly token = signal<string | null>(this._read(TOKEN_KEY));
  readonly userId = signal<string | null>(this._read(USER_ID_KEY));
  readonly orgId = signal<string | null>(this._read(ORG_ID_KEY));
  readonly fullName = signal<string | null>(this._read(FULL_NAME_KEY));

  isAuthenticated(): boolean {
    const t = this.token();
    if (!t) return false;
    const exp = this._read(EXPIRES_KEY);
    if (!exp) return false;
    return new Date(exp).getTime() > Date.now();
  }

  save(payload: {
    staff_token: string;
    expires_at: string;
    user_id: string;
    org_id: string;
    full_name: string;
  }): void {
    localStorage.setItem(TOKEN_KEY, payload.staff_token);
    localStorage.setItem(EXPIRES_KEY, payload.expires_at);
    localStorage.setItem(USER_ID_KEY, payload.user_id);
    localStorage.setItem(ORG_ID_KEY, payload.org_id);
    localStorage.setItem(FULL_NAME_KEY, payload.full_name);
    this.token.set(payload.staff_token);
    this.userId.set(payload.user_id);
    this.orgId.set(payload.org_id);
    this.fullName.set(payload.full_name);
  }

  clear(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXPIRES_KEY);
    localStorage.removeItem(USER_ID_KEY);
    localStorage.removeItem(ORG_ID_KEY);
    localStorage.removeItem(FULL_NAME_KEY);
    this.token.set(null);
    this.userId.set(null);
    this.orgId.set(null);
    this.fullName.set(null);
  }

  private _read(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
}
