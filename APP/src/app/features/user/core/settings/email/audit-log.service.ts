/**
 * Audit-log API service (tasks/email-inbound-audit-verdicts Step 3).
 *
 * Wraps ``GET /api/v1/admin/email-inbound-deliveries`` — a
 * platform-staff-only, cross-tenant audit log of every Mailgun
 * webhook receipt.
 *
 * Guarded by ``mailgun.inbound.dlq.manage`` on the backend (same key
 * the DLQ admin endpoints use — see backend router docstring for the
 * rationale + eventual migration path to a proper ``platform.admin``).
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type AuditOutcome =
  | 'enqueued'
  | 'signature_rejected'
  | 'replay_rejected'
  | 'timestamp_rejected'
  | 'size_rejected_before_download';

export interface InboundDelivery {
  id: string;
  received_at: string;
  signature_status: string;
  replay_status: string;
  timestamp_status: string;
  outcome: AuditOutcome;
  mailgun_delivery_id: string | null;
  mailgun_message_id: string | null;
  recipient: string | null;
  sender: string | null;
  payload_size_bytes: number | null;
  attachment_count: number | null;
  client_ip: string | null;
}

export interface InboundDeliveriesListResponse {
  items: InboundDelivery[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditLogListParams {
  outcome?: AuditOutcome;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
}

@Injectable({ providedIn: 'root' })
export class AuditLogService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/admin/email-inbound-deliveries`;

  list(params: AuditLogListParams = {}): Observable<InboundDeliveriesListResponse> {
    let httpParams = new HttpParams();
    if (params.outcome) httpParams = httpParams.set('outcome', params.outcome);
    if (params.from) httpParams = httpParams.set('from', params.from);
    if (params.to) httpParams = httpParams.set('to', params.to);
    if (params.page != null) httpParams = httpParams.set('page', String(params.page));
    if (params.page_size != null)
      httpParams = httpParams.set('page_size', String(params.page_size));
    return this.http.get<InboundDeliveriesListResponse>(this.base, { params: httpParams });
  }
}
