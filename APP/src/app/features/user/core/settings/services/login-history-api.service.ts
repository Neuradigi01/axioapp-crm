import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/**
 * One row from `GET /api/v1/auth/sessions`. Shape mirrors the backend
 * `SessionOut` schema in `core/auth/schemas.py`. The Settings → Login
 * history tab marks the row with `is_current=true` as "This session"
 * and disables Sign-out on it (the caller must use POST /auth/logout
 * to end the current session).
 */
export interface SessionRow {
  id: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  ip: string | null;
  ua: string | null;
  is_current: boolean;
}

interface SessionListResponse {
  sessions: SessionRow[];
}

@Injectable({ providedIn: 'root' })
export class LoginHistoryApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/auth/sessions`;

  list(): Observable<SessionListResponse> {
    return this.http.get<SessionListResponse>(this.base);
  }

  revoke(sessionId: string): Observable<{ success: boolean }> {
    return this.http.post<{ success: boolean }>(
      `${this.base}/${sessionId}/revoke`,
      {},
    );
  }
}
