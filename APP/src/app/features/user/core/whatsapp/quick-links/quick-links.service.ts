import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface QuickLink {
  id: string;
  code: string;
  label: string;
  phone_number: string;
  prefilled_message: string | null;
  click_count: number;
  scan_count: number;
  attributed_conversation_count: number;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuickLinkPage {
  items: QuickLink[];
  total: number;
  page: number;
  size: number;
}

export interface QuickLinkUpsert {
  label: string;
  phone_number: string;
  prefilled_message?: string | null;
}

export interface QuickLinkStats {
  id: string;
  code: string;
  label: string;
  clicks: number;
  scans: number;
  attributed_conversations: number;
  recent_clicks: Array<{
    id: string;
    source: 'link' | 'qr';
    ua_family: string | null;
    referrer: string | null;
    recorded_at: string;
    matched: boolean;
  }>;
}

/**
 * Quick-links API client (Step 26).
 *
 * All authenticated endpoints gate server-side on
 * `whatsapp.automation.manage` (reused from Step 17 — same
 * Owner / Admin audience). The QR PNG / SVG URLs are returned
 * raw so the UI can `<a href>` them directly without an extra
 * blob round-trip.
 */
@Injectable({ providedIn: 'root' })
export class QuickLinksService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/quick-links`;

  list(page = 1, size = 50): Observable<QuickLinkPage> {
    const params = new HttpParams().set('page', page).set('size', size);
    return this.http.get<QuickLinkPage>(this.base, { params });
  }

  create(body: QuickLinkUpsert): Observable<QuickLink> {
    return this.http.post<QuickLink>(this.base, body);
  }

  update(id: string, body: Partial<QuickLinkUpsert>): Observable<QuickLink> {
    return this.http.patch<QuickLink>(`${this.base}/${id}`, body);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  stats(id: string): Observable<QuickLinkStats> {
    return this.http.get<QuickLinkStats>(`${this.base}/${id}/stats`);
  }

  /** QR endpoints return raw image bytes; we expose URLs so the
   *  UI can use them as `<img src>` / `<a href>` directly. The
   *  browser sends auth cookies / Authorization header (jwt
   *  interceptor) so server-side RLS still scopes to the user's org. */
  qrPngUrl(id: string, size = 512): string {
    return `${this.base}/${id}/qr.png?size=${size}`;
  }

  qrSvgUrl(id: string): string {
    return `${this.base}/${id}/qr.svg`;
  }

  /** Public 302 endpoint that the QR encodes. Visible to anyone — the
   *  UI shows it for clipboard copy. */
  publicUrl(code: string): string {
    const root = environment.apiBaseUrl.replace(/\/api\/v1\/?$/, '');
    return `${root}/wa/${code}`;
  }
}
