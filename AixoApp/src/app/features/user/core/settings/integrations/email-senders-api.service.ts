/**
 * Typed HTTP wrappers for the per-org email-sender identity surface.
 *
 * Backing endpoints live in `core/email_senders/router.py` and are
 * gated by `email.accounts.manage`:
 *
 *   - `list()`             — `GET /email-senders/` (unified list of
 *                            verified SMTP senders + live OAuth
 *                            mailboxes).
 *   - `createSmtp(...)`    — `POST /email-senders/smtp` (inserts +
 *                            emails the 6-digit verification code
 *                            to the from-address using the supplied
 *                            SMTP creds; SMTP failure surfaces as 400
 *                            with the provider's message).
 *   - `verify(id, code)`   — `POST /email-senders/smtp/{id}/verify`.
 *   - `resendCode(id)`     — `POST /email-senders/smtp/{id}/resend-code`.
 *   - `setDefault(id)`     — `POST /email-senders/smtp/{id}/set-default`.
 *   - `delete(id)`         — `DELETE /email-senders/{id}` (SMTP only;
 *                            OAuth deletion continues to use the
 *                            existing `/email/accounts/{id}` endpoint).
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type SmtpTlsMode = 'starttls' | 'tls' | 'none';

export type UnifiedSenderKind = 'gmail' | 'microsoft' | 'smtp';

export interface UnifiedSender {
  kind: UnifiedSenderKind;
  id: string;
  from_address: string;
  display_name: string | null;
  verified: boolean;
  is_default: boolean;
}

export interface SmtpSender {
  id: string;
  from_address: string;
  display_name: string | null;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  tls_mode: SmtpTlsMode;
  verified_at: string | null;
  is_default: boolean;
  created_at: string;
}

export interface CreateSmtpSenderPayload {
  from_address: string;
  display_name: string | null;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  tls_mode: SmtpTlsMode;
}

@Injectable({ providedIn: 'root' })
export class EmailSendersApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/email-senders`;

  list(): Observable<UnifiedSender[]> {
    return this.http.get<UnifiedSender[]>(`${this.base}/`);
  }

  createSmtp(payload: CreateSmtpSenderPayload): Observable<SmtpSender> {
    return this.http.post<SmtpSender>(`${this.base}/smtp`, payload);
  }

  verify(id: string, code: string): Observable<SmtpSender> {
    return this.http.post<SmtpSender>(`${this.base}/smtp/${id}/verify`, { code });
  }

  resendCode(id: string): Observable<SmtpSender> {
    return this.http.post<SmtpSender>(`${this.base}/smtp/${id}/resend-code`, {});
  }

  setDefault(id: string): Observable<SmtpSender> {
    return this.http.post<SmtpSender>(`${this.base}/smtp/${id}/set-default`, {});
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
