import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

/** Body shape for `PATCH /api/v1/users/me`. */
export interface MeUpdatePayload {
  full_name?: string;
  phone?: string | null;
}

/** Body shape for `POST /api/v1/users/me/password`. */
export interface PasswordChangePayload {
  current_password: string;
  new_password: string;
  sign_out_others: boolean;
}

/**
 * Self-service profile API — the two write endpoints introduced in
 * step 2.5.5. Read access is via `FurnitureAuthService.me()`.
 *
 * Kept as a thin wrapper so the page component just calls signals →
 * HTTP without inlining URLs.
 */
@Injectable({ providedIn: 'root' })
export class ProfileApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/users/me`;

  updateMe(payload: MeUpdatePayload): Observable<unknown> {
    return this.http.patch(this.base, payload);
  }

  changePassword(payload: PasswordChangePayload): Observable<void> {
    return this.http.post<void>(`${this.base}/password`, payload);
  }
}
