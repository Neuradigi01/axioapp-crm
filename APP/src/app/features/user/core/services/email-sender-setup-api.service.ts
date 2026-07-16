/**
 * Typed HTTP wrappers for the sender-setup surface (Step 07b).
 *
 * Backing endpoints live in `core/email_sender_setup/router.py` and are
 * gated by `email.accounts.admin` (Owner + Admin templates only). Five
 * operations:
 *
 *  - `listDomains()`               — `GET /email-sender-setup/domains`.
 *  - `createDomain({domain})`      — `POST /email-sender-setup/domains`.
 *  - `dnsRecords(domainId)`        — `GET /email-sender-setup/domains/{id}/dns-records`.
 *  - `verifyDomain(domainId)`      — `POST /email-sender-setup/domains/{id}/verify`.
 *                                    Rate-limited to once/60s per (org,
 *                                    domain) — a 429 signals the caller
 *                                    to wait and re-try.
 *  - `deleteDomain(domainId)`      — `DELETE /email-sender-setup/domains/{id}`.
 *                                    400 when a scheduled/running
 *                                    campaign still points at a mailbox
 *                                    on this domain.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

export interface EmailSenderDomain {
  id: string;
  org_id: string;
  domain: string;
  spf_verified: boolean;
  dkim_verified: boolean;
  dmarc_verified: boolean;
  spf_last_checked_at: string | null;
  dkim_last_checked_at: string | null;
  dmarc_last_checked_at: string | null;
  dkim_selector: string;
  dkim_public_key: string;
  created_at: string;
}

export interface EmailSenderDnsRecord {
  type: 'TXT' | 'CNAME';
  host: string;
  value: string;
  purpose: 'spf' | 'dkim' | 'dmarc';
}

export interface EmailSenderDnsRecordsResponse {
  domain: string;
  records: EmailSenderDnsRecord[];
}

export interface EmailSenderVerifyResponse {
  id: string;
  domain: string;
  spf_verified: boolean;
  dkim_verified: boolean;
  dmarc_verified: boolean;
  fully_verified: boolean;
  last_checked_at: string;
}

@Injectable({ providedIn: 'root' })
export class EmailSenderSetupApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/email-sender-setup`;

  listDomains(): Observable<EmailSenderDomain[]> {
    return this.http.get<EmailSenderDomain[]>(`${this.base}/domains`);
  }

  createDomain(domain: string): Observable<EmailSenderDomain> {
    return this.http.post<EmailSenderDomain>(`${this.base}/domains`, { domain });
  }

  dnsRecords(domainId: string): Observable<EmailSenderDnsRecordsResponse> {
    return this.http.get<EmailSenderDnsRecordsResponse>(
      `${this.base}/domains/${domainId}/dns-records`,
    );
  }

  verifyDomain(domainId: string): Observable<EmailSenderVerifyResponse> {
    return this.http.post<EmailSenderVerifyResponse>(`${this.base}/domains/${domainId}/verify`, {});
  }

  deleteDomain(domainId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/domains/${domainId}`);
  }
}
