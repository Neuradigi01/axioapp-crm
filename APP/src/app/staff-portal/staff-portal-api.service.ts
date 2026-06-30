import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { StaffSessionService } from './staff-session.service';

/** GET /staff-portal/users picker row. */
export interface StaffPickerUser {
  id: string;
  full_name: string;
  avatar: string | null;
}

export interface StaffLoginResponse {
  staff_token: string;
  expires_at: string;
  user_id: string;
  org_id: string;
}

export interface StaffMeOut {
  id: string;
  org_id: string;
  full_name: string;
  email: string;
}

export interface StaffPerformance {
  user_id: string;
  leads_converted: number;
  leads_active: number;
  sales: string;
  monthly_target: string;
  target_progress_pct: number | null;
  rating: string;
  commission_rate: string;
}

export interface StaffAttendance {
  id: string;
  org_id: string;
  user_id: string;
  clock_in_at: string;
  clock_out_at: string | null;
  hours: string | null;
  date: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface StaffActivity {
  id: string;
  org_id: string;
  entity_type: string;
  entity_id: string;
  type: string;
  payload: Record<string, unknown>;
  user_id: string | null;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class StaffPortalApiService {
  private readonly http = inject(HttpClient);
  private readonly session = inject(StaffSessionService);
  private readonly base = `${environment.apiBaseUrl}/staff-portal`;

  // --- unauthenticated ---

  listUsers(orgSlug: string): Observable<StaffPickerUser[]> {
    const params = new HttpParams().set('org_slug', orgSlug);
    return this.http.get<StaffPickerUser[]>(`${this.base}/users`, { params });
  }

  login(orgSlug: string, userId: string, pin: string): Observable<StaffLoginResponse> {
    return this.http.post<StaffLoginResponse>(`${this.base}/auth/login`, {
      org_slug: orgSlug,
      user_id: userId,
      pin,
    });
  }

  // --- authenticated (scope="staff") ---

  me(): Observable<StaffMeOut> {
    return this.http.get<StaffMeOut>(`${this.base}/me`, {
      headers: this._authHeaders(),
    });
  }

  performance(): Observable<StaffPerformance> {
    return this.http.get<StaffPerformance>(`${this.base}/me/performance`, {
      headers: this._authHeaders(),
    });
  }

  attendance(from?: string, to?: string): Observable<StaffAttendance[]> {
    let params = new HttpParams();
    if (from) params = params.set('from', from);
    if (to) params = params.set('to', to);
    return this.http.get<StaffAttendance[]>(`${this.base}/me/attendance`, {
      params,
      headers: this._authHeaders(),
    });
  }

  activity(limit = 100): Observable<StaffActivity[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http.get<StaffActivity[]>(`${this.base}/me/activity`, {
      params,
      headers: this._authHeaders(),
    });
  }

  clockIn(notes?: string): Observable<StaffAttendance> {
    return this.http.post<StaffAttendance>(
      `${this.base}/me/clock-in`,
      { notes: notes ?? null },
      { headers: this._authHeaders() },
    );
  }

  clockOut(notes?: string): Observable<StaffAttendance> {
    return this.http.post<StaffAttendance>(
      `${this.base}/me/clock-out`,
      { notes: notes ?? null },
      { headers: this._authHeaders() },
    );
  }

  private _authHeaders(): HttpHeaders {
    const t = this.session.token();
    return new HttpHeaders(t ? { Authorization: `Bearer ${t}` } : {});
  }
}
