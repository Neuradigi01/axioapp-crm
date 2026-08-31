import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

/** Joined `users` + optional `staff_profiles` row (GET /staff item). */
export interface StaffListItem {
  id: string;
  org_id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role_id: string;
  is_active: boolean;
  commission_rate: string | null;
  monthly_target: string | null;
  rating: string | null;
  employment_status: 'active' | 'leave' | 'terminated' | null;
  joined_at: string | null;
}

export interface StaffProfileUpsert {
  commission_rate: string | number;
  monthly_target: string | number;
  rating: string | number;
  employment_status?: 'active' | 'leave' | 'terminated';
  joined_at?: string;
}

export interface StaffProfileOut {
  user_id: string;
  org_id: string;
  commission_rate: string;
  monthly_target: string;
  rating: string;
  employment_status: 'active' | 'leave' | 'terminated';
  joined_at: string;
  created_at: string;
  updated_at: string;
}

export interface PerformanceOut {
  user_id: string;
  leads_converted: number;
  leads_active: number;
  sales: string;
  monthly_target: string;
  target_progress_pct: number | null;
  rating: string;
  commission_rate: string;
}

export interface AttendanceOut {
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

export interface StaffWithPerformance {
  staff: StaffListItem;
  performance: PerformanceOut;
}

@Injectable({ providedIn: 'root' })
export class StaffApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/staff`;

  list(): Observable<StaffListItem[]> {
    return this.http.get<StaffListItem[]>(this.base);
  }

  /** Distinct staff members present (at least one attendance row) today. */
  presentToday(): Observable<{ count: number }> {
    return this.http.get<{ count: number }>(`${this.base}/present-today`);
  }

  /** Sums of `Invoice.total` over paid invoices (all-time and today).
   * Powers the Total Revenue + Today's Revenue KPI cards. */
  revenueTotals(): Observable<{ total: number; today: number }> {
    return this.http.get<{ total: number; today: number }>(`${this.base}/revenue-totals`);
  }

  upsertProfile(userId: string, payload: StaffProfileUpsert): Observable<StaffProfileOut> {
    return this.http.put<StaffProfileOut>(`${this.base}/${userId}`, payload);
  }

  performance(userId: string): Observable<PerformanceOut> {
    return this.http.get<PerformanceOut>(`${this.base}/${userId}/performance`);
  }

  /** Batch-fetch performance for many users in a single request.
   *  Used by ``loadWithPerformance()`` so the staff list page issues
   *  one POST instead of one GET per staff row. Capped server-side at
   *  200 ids per call. */
  performanceBulk(userIds: string[]): Observable<PerformanceOut[]> {
    return this.http.post<PerformanceOut[]>(`${this.base}/performance/bulk`, {
      user_ids: userIds,
    });
  }

  attendance(userId: string, from?: string, to?: string): Observable<AttendanceOut[]> {
    const params = buildHttpParams({ from, to });
    return this.http.get<AttendanceOut[]>(`${this.base}/${userId}/attendance`, { params });
  }

  activity(userId: string, limit = 100): Observable<StaffActivity[]> {
    const params = buildHttpParams({ limit });
    return this.http.get<StaffActivity[]>(`${this.base}/${userId}/activity`, { params });
  }

  clockIn(userId: string, notes?: string): Observable<AttendanceOut> {
    return this.http.post<AttendanceOut>(`${this.base}/${userId}/clock-in`, {
      notes: notes ?? null,
    });
  }

  clockOut(userId: string, notes?: string): Observable<AttendanceOut> {
    return this.http.post<AttendanceOut>(`${this.base}/${userId}/clock-out`, {
      notes: notes ?? null,
    });
  }

  /**
   * Fetches the staff list and joins each row with its performance
   * payload. Uses the ``POST /staff/performance/bulk`` batch endpoint
   * so the whole page renders with TWO API calls (list + bulk perf)
   * instead of ``1 + N`` (one GET per staff member). The previous
   * fan-out multiplied the SQL cost by ``3 × N`` on the backend too —
   * batch runs a single ``GROUP BY assigned_to, status`` for all users.
   */
  loadWithPerformance(): Observable<StaffWithPerformance[]> {
    return new Observable<StaffWithPerformance[]>((subscriber) => {
      const sub = this.list().subscribe({
        next: (staff) => {
          if (staff.length === 0) {
            subscriber.next([]);
            subscriber.complete();
            return;
          }
          const ids = staff.map((s) => s.id);
          this.performanceBulk(ids).subscribe({
            next: (perfs) => {
              const perfByUser = new Map<string, PerformanceOut>();
              for (const p of perfs) {
                perfByUser.set(p.user_id, p);
              }
              const rows: StaffWithPerformance[] = staff.map((s) => ({
                staff: s,
                // Backend returns one entry per requested id in input order,
                // so the lookup below always hits. Guard is defensive.
                performance:
                  perfByUser.get(s.id) ??
                  ({
                    user_id: s.id,
                    leads_converted: 0,
                    leads_active: 0,
                    sales: '0',
                    monthly_target: '0',
                    target_progress_pct: null,
                    rating: '0',
                    commission_rate: '0',
                  } satisfies PerformanceOut),
              }));
              subscriber.next(rows);
              subscriber.complete();
            },
            error: (e) => subscriber.error(e),
          });
        },
        error: (e) => subscriber.error(e),
      });
      return () => sub.unsubscribe();
    });
  }
}
