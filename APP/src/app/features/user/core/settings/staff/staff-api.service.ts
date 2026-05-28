import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/** Per-entity open-record counts for one user. Drives the
 * deactivation modal's "what will be transferred" table. */
export interface OpenRecordsCounts {
  user_id: string;
  contacts: number;
  leads: number;
  walk_ins: number;
  appointments: number;
  tasks: number;
  total: number;
}

/** Summary of an atomic bulk-reassign. `transferred` is the per-entity
 * row-count; `audit_activities_written` is the total reassign-activity
 * count — useful for the success message. */
export interface TransferRecordsResponse {
  from_user_id: string;
  to_user_id: string;
  transferred: Record<string, number>;
  total: number;
  audit_activities_written: number;
}

/** Body of `POST /users/{id}/transfer-records`. `entities` defaults
 * to all five on the backend; passing an explicit subset is rare. */
export interface TransferRecordsRequest {
  to_user_id: string;
  entities?: string[];
  reason?: string | null;
}

/** Per-user row in the Workload table. */
export interface WorkloadUser {
  user_id: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  counts: OpenRecordsCounts;
}

export interface WorkloadReport {
  users: WorkloadUser[];
  as_of: string;
}

@Injectable({ providedIn: 'root' })
export class StaffApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  /** Per-entity open-record counts for `userId`. Reads `users.read`. */
  getOpenRecordsCounts(userId: string): Observable<OpenRecordsCounts> {
    return this.http.get<OpenRecordsCounts>(
      `${this.base}/users/${userId}/open-records-counts`,
    );
  }

  /** Atomic bulk-reassign across the named entities (defaults to all
   * five on the server). Each reassigned row gets a `reassign`
   * activity carrying `reason`. */
  transferRecords(
    userId: string,
    payload: TransferRecordsRequest,
  ): Observable<TransferRecordsResponse> {
    return this.http.post<TransferRecordsResponse>(
      `${this.base}/users/${userId}/transfer-records`,
      {
        to_user_id: payload.to_user_id,
        entities: payload.entities,
        reason: payload.reason ?? null,
      },
    );
  }

  /** Per-user workload across the org. Drives the Workload sub-tab. */
  getWorkload(activeOnly = true): Observable<WorkloadReport> {
    return this.http.get<WorkloadReport>(`${this.base}/reports/workload`, {
      params: { active_only: String(activeOnly) },
    });
  }
}
