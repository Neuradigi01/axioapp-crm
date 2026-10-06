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
 *   - `setDefault(id)`     — `POST /email-senders/{id}/set-default`
 *                            (polymorphic — SMTP or OAuth mailbox).
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

/** SMTP-sender reply-capture surface exposed by the mailgun-inbound
 *  track. `null` for OAuth rows (Gmail/Microsoft handle inbound
 *  replies via their own sync) and for SMTP rows when the deploy
 *  hasn't opted into Mailgun inbound (INBOUND_EMAIL_DOMAIN empty).
 *
 *  `address` is server-composed (`in_<token>@<INBOUND_EMAIL_DOMAIN>`)
 *  — never construct it client-side; that would leak deploy config
 *  into the frontend and hard-code sandbox-vs-prod. */
export interface InboundReplyAddress {
  token: string;
  address: string;
  capture_enabled: boolean;
}

export interface UnifiedSender {
  kind: UnifiedSenderKind;
  id: string;
  from_address: string;
  display_name: string | null;
  verified: boolean;
  is_default: boolean;
  /** OAuth-only health fields (`null` for SMTP). Backend
   *  `UnifiedSenderOut` populates them so the card can render a
   *  session-refresh countdown + a prominent "reconnect required"
   *  banner when Google/Microsoft revoke the grant. Silent
   *  revocations were the reason yesterday's appointment-assigned
   *  emails failed to land. */
  token_expires_at?: string | null;
  sync_state?: string | null;
  last_sync_error?: string | null;
  /** SMTP-only reply-capture block. `null` for OAuth rows or when
   *  the deploy hasn't wired the Mailgun receiving domain. Nullable
   *  end-to-end so the card renders cleanly during phased rollout
   *  when the backend hasn't shipped INBOUND_EMAIL_DOMAIN yet. */
  inbound_reply_address?: InboundReplyAddress | null;
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
  /** Reply-capture block, matching `UnifiedSender.inbound_reply_address`. */
  inbound_reply_address?: InboundReplyAddress | null;
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

/** True iff this OAuth sender's grant is dead — Google/Microsoft
 *  rejected the refresh token, so the next send will 401. Shared by
 *  the sender card's "Reconnect needed" pill and the Integrations
 *  page's Email tile status. */
export function isSenderOauthRevoked(row: UnifiedSender): boolean {
  if (row.kind === 'smtp') return false;
  if (row.sync_state === 'error') return true;
  const err = (row.last_sync_error ?? '').toLowerCase();
  if (!err) return false;
  return (
    err.includes('invalid_grant') ||
    err.includes('revoked') ||
    err.includes('unauthorized') ||
    err.includes('token has been expired')
  );
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

  /** Mark this sender — SMTP or OAuth (Gmail / Microsoft) — as the
   *  org's default. Backend returns 204; the caller re-fetches the
   *  unified list to pick up the new default badge. */
  setDefault(id: string): Observable<void> {
    return this.http.post<void>(`${this.base}/${id}/set-default`, {});
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  /** mailgun-inbound track: flip the per-sender opt-out for Reply-To
   *  rewriting. `capture=false` means outbound from this SMTP sender
   *  leaves the caller-supplied Reply-To alone; replies go back to
   *  the SMTP mailbox instead of the CRM. */
  setCaptureToggle(id: string, capture: boolean): Observable<SmtpSender> {
    return this.http.patch<SmtpSender>(`${this.base}/smtp/${id}/capture-toggle`, {
      capture,
    });
  }
}
