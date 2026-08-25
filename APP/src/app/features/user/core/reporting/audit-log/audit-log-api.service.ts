import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from '../../auth/token-storage.service';

/**
 * Wire shape of a single ``tbl_audit_logs`` row as returned by
 * ``GET /api/v1/audit-logs``. Mirrors ``AuditLogOut`` on the backend.
 */
export interface AuditLogRow {
  readonly id: string;
  readonly org_id: string;
  readonly user_id: string | null;
  readonly action: string;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly before: Record<string, unknown> | null;
  readonly after: Record<string, unknown> | null;
  readonly ip: string | null;
  readonly ua: string | null;
  readonly created_at: string;
}

export interface AuditLogPage {
  readonly items: readonly AuditLogRow[];
  readonly total: number;
  readonly page: number;
  readonly size: number;
}

export interface AuditLogFilters {
  action?: string | null;
  entity_type?: string | null;
  user_id?: string | null;
  from?: string | null;
  to?: string | null;
  page?: number;
  size?: number;
}

/**
 * Client for the audit-log module. Gated server-side on the
 * ``audit.full_log`` feature — calling this from a non-Enterprise
 * plan returns HTTP 402 with a ``feature_locked`` payload the
 * caller can render via ``crm-locked-feature``. Frontend gating
 * (``FeatureAccessService.hasFeature``) prevents the call altogether
 * so the 402 is a defence-in-depth safety net, not the primary UX.
 */
@Injectable({ providedIn: 'root' })
export class AuditLogApiService {
  private readonly http = inject(HttpClient);
  private readonly tokens = inject(TokenStorageService);
  private readonly base = `${environment.apiBaseUrl}/audit-logs`;

  list(filters: AuditLogFilters = {}): Observable<AuditLogPage> {
    return this.http.get<AuditLogPage>(this.base, {
      params: this._buildParams(filters),
    });
  }

  /** Trigger a CSV download in-browser. Uses ``fetch`` + Blob rather
   *  than the HttpClient because Angular's HttpClient can't stream a
   *  file download directly into the browser's Save dialog — a plain
   *  Blob URL + `<a download>` click is the standard pattern for this
   *  and avoids the "load 25 MB into memory as JSON first" foot-gun. */
  async downloadCsv(filters: AuditLogFilters = {}): Promise<void> {
    const params = this._buildParams(filters);
    const url = new URL(`${this.base}/export.csv`, window.location.origin);
    // Reconstruct the query string from HttpParams so both list() and
    // downloadCsv() encode identically — the operator's exported CSV
    // matches exactly what's shown in the paginated table.
    params.keys().forEach((k) => {
      const v = params.get(k);
      if (v !== null) url.searchParams.set(k, v);
    });

    const token = this.tokens.getAccess();
    const response = await fetch(url.toString(), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw new Error(`Export failed: ${response.status} ${response.statusText}`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    // Server sets the ``Content-Disposition`` filename; browsers honour
    // it when the `download` attribute is empty. Setting a hint here
    // covers browsers that ignore the header on same-origin downloads.
    link.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    // Revoke on next tick so Chrome has a moment to actually start the
    // download before the URL is invalidated.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  private _buildParams(filters: AuditLogFilters): HttpParams {
    let params = new HttpParams();
    if (filters.action) params = params.set('action', filters.action);
    if (filters.entity_type) params = params.set('entity_type', filters.entity_type);
    if (filters.user_id) params = params.set('user_id', filters.user_id);
    if (filters.from) params = params.set('from', filters.from);
    if (filters.to) params = params.set('to', filters.to);
    if (filters.page !== undefined) params = params.set('page', String(filters.page));
    if (filters.size !== undefined) params = params.set('size', String(filters.size));
    return params;
  }
}
