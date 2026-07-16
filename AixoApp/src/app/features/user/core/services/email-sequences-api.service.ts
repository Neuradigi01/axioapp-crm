/**
 * Typed HTTP wrappers for the email-sequences surface.
 *
 * Endpoints (all under `${apiBaseUrl}/email/sequences`):
 *
 *  - `listSequences(filters?)` — paginated GET; `q` ILIKEs on name.
 *  - `getSequence(id)`        — single read; payload includes the
 *                                ordered `steps[]` array.
 *  - `createSequence(payload)`— POST; backend materialises step rows
 *                                with dense 1-based `step_order`.
 *  - `updateSequence(id, payload)` — PATCH; `steps` is FULL-replace
 *                                when provided; backend 409s when
 *                                active enrollments exist.
 *  - `deleteSequence(id)`     — soft delete (preserves enrollment FK
 *                                references; scheduler completes
 *                                active enrollments on next tick).
 *  - `enroll(seqId, body)`    — bulk-enroll contacts (+ optional
 *                                same-length lead_ids).
 *  - `listEnrollments(filters?)`     — paginated GET; filters by
 *                                       `sequence_id` / `contact_id` /
 *                                       `state` / `page` / `size`.
 *  - `pauseEnrollment(id)`    — POST; flips to `paused_manual` and
 *                                bulk-skips pending step rows.
 *  - `resumeEnrollment(id)`   — POST; flips back to `active` and
 *                                inserts a fresh pending step row at
 *                                `now + current_step.delay_days`.
 *  - `cancelEnrollment(id)`   — POST; terminal cancel.
 *
 * Auth: global `authInterceptor` injects the JWT; `retryInterceptor`
 * handles transient failures on GETs.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

export type EnrollmentState =
  | 'active'
  | 'completed'
  | 'paused_on_reply'
  | 'paused_manual'
  | 'cancelled';

export interface EmailSequenceStep {
  id: string;
  sequence_id: string;
  step_order: number;
  delay_days: number;
  template_id: string;
}

export interface EmailSequence {
  id: string;
  org_id: string;
  name: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  steps: EmailSequenceStep[];
}

export interface EmailSequenceListResponse {
  items: EmailSequence[];
  total: number;
  page: number;
  size: number;
}

export interface SequenceStepCreate {
  delay_days: number;
  template_id: string;
}

export interface SequenceCreatePayload {
  name: string;
  is_active?: boolean;
  steps: SequenceStepCreate[];
}

export interface SequenceUpdatePayload {
  name?: string;
  is_active?: boolean;
  /** When provided, FULL-replaces the sequence's step list. Backend
   *  rejects with 409 if active/paused enrollments exist. */
  steps?: SequenceStepCreate[];
}

export interface EnrollmentRequest {
  contact_ids: string[];
  /** Optional; same length as `contact_ids` when provided. */
  lead_ids?: string[];
}

export interface EnrollmentResultRow {
  contact_id: string;
  enrollment_id: string | null;
  enrolled: boolean;
  skip_reason: string | null;
}

export interface EnrollmentResponse {
  results: EnrollmentResultRow[];
  enrolled_count: number;
  skipped_count: number;
}

export interface Enrollment {
  id: string;
  org_id: string;
  sequence_id: string;
  contact_id: string;
  lead_id: string | null;
  enrolled_by: string;
  enrolled_at: string;
  state: EnrollmentState;
  state_changed_at: string;
  current_step_order: number;
}

export interface EnrollmentListResponse {
  items: Enrollment[];
  total: number;
  page: number;
  size: number;
}

@Injectable({ providedIn: 'root' })
export class EmailSequencesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/email/sequences`;

  // --- Sequences --------------------------------------------------------

  listSequences(filters?: {
    q?: string;
    is_active?: boolean;
    page?: number;
    size?: number;
  }): Observable<EmailSequenceListResponse> {
    let params = new HttpParams();
    if (filters?.q) params = params.set('q', filters.q);
    if (filters?.is_active !== undefined) {
      params = params.set('is_active', String(filters.is_active));
    }
    if (filters?.page) params = params.set('page', String(filters.page));
    if (filters?.size) params = params.set('size', String(filters.size));
    return this.http.get<EmailSequenceListResponse>(this.base, { params });
  }

  getSequence(id: string): Observable<EmailSequence> {
    return this.http.get<EmailSequence>(`${this.base}/${id}`);
  }

  createSequence(payload: SequenceCreatePayload): Observable<EmailSequence> {
    return this.http.post<EmailSequence>(this.base, payload);
  }

  updateSequence(id: string, payload: SequenceUpdatePayload): Observable<EmailSequence> {
    return this.http.patch<EmailSequence>(`${this.base}/${id}`, payload);
  }

  deleteSequence(id: string): Observable<EmailSequence> {
    return this.http.delete<EmailSequence>(`${this.base}/${id}`);
  }

  // --- Enrollment -------------------------------------------------------

  enroll(sequenceId: string, payload: EnrollmentRequest): Observable<EnrollmentResponse> {
    return this.http.post<EnrollmentResponse>(`${this.base}/${sequenceId}/enroll`, payload);
  }

  listEnrollments(filters?: {
    sequence_id?: string;
    contact_id?: string;
    state?: EnrollmentState;
    page?: number;
    size?: number;
  }): Observable<EnrollmentListResponse> {
    let params = new HttpParams();
    if (filters?.sequence_id) {
      params = params.set('sequence_id', filters.sequence_id);
    }
    if (filters?.contact_id) {
      params = params.set('contact_id', filters.contact_id);
    }
    if (filters?.state) params = params.set('state', filters.state);
    if (filters?.page) params = params.set('page', String(filters.page));
    if (filters?.size) params = params.set('size', String(filters.size));
    return this.http.get<EnrollmentListResponse>(`${this.base}/enrollments`, { params });
  }

  pauseEnrollment(id: string): Observable<Enrollment> {
    return this.http.post<Enrollment>(`${this.base}/enrollments/${id}/pause`, {});
  }

  resumeEnrollment(id: string): Observable<Enrollment> {
    return this.http.post<Enrollment>(`${this.base}/enrollments/${id}/resume`, {});
  }

  cancelEnrollment(id: string): Observable<Enrollment> {
    return this.http.post<Enrollment>(`${this.base}/enrollments/${id}/cancel`, {});
  }
}
