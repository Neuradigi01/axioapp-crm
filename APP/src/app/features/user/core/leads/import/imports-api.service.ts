import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../shared/services/query-builder';

/**
 * Typed Angular wrapper for the backend bulk-import endpoints
 * (Steps 1–3 of the bulk-import track).
 *
 * Endpoint catalogue:
 *
 *   POST   /leads/import/upload              → multipart upload
 *   GET    /leads/import                     → paginated list
 *   GET    /leads/import/{id}                → one row
 *   POST   /leads/import/{id}/commit         → commit mapping → run job
 *   POST   /leads/import/{id}/cancel         → cancel pre-terminal
 *   GET    /leads/import/{id}/errors.csv     → download per-import errors
 *   GET    /leads/import/{id}/skipped.csv    → download per-import duplicates
 *   GET    /leads/import/targets             → mappable CRM fields
 *   GET    /leads/import/presets             → system + org presets
 *   POST   /leads/import/presets             → save an org preset
 *   DELETE /leads/import/presets/{id}        → remove an org preset
 *
 * Lives under `core/leads/import/` so Step 5 (mapping UI) and Step 6
 * (history page) reuse the same service.
 */

export type SourcePlatform =
  | 'zoho'
  | 'hubspot'
  | 'salesforce'
  | 'freshsales'
  | 'generic_csv'
  | 'custom';

export type LeadImportStatus =
  | 'awaiting_mapping'
  | 'mapping_committed'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface LeadImport {
  id: string;
  org_id: string;
  uploaded_by: string;
  name: string;
  source_platform: string;
  original_filename: string;
  storage_path: string;
  byte_size: number;
  row_count_estimate: number;
  mime_type: string;
  status: LeadImportStatus;
  mapping: Record<string, string | null> | null;
  counts: ImportCounts | null;
  error_report_path: string | null;
  skipped_report_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportCounts {
  imported?: number;
  duplicates_skipped?: number;
  errors?: number;
  fatal_error?: string;
  /** Bucketed error reasons — `{ "invalid date 'next' …": 10, … }`. Populated by
   * the processor so the result page can show a per-reason tally without
   * requiring an errors.csv download. Empty when the run had no errors. */
  error_reasons?: Record<string, number>;
  /** Bucketed skip reasons — currently one flavour per contact-match key
   * (phone / email / both), all under the "open lead already exists" umbrella
   * since that's the only condition that triggers a merge in v1. */
  skipped_reasons?: Record<string, number>;
}

export interface LeadImportListResponse {
  items: LeadImport[];
  total: number;
  page: number;
  size: number;
}

export interface MappingTarget {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  custom: boolean;
}

export interface ImportPreset {
  id: string;
  org_id: string | null; // null = system preset
  source_platform: string;
  name: string;
  mapping: Record<string, string | null>;
  is_system: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PresetCreatePayload {
  name?: string | null;
  source_platform: SourcePlatform;
  mapping: Record<string, string | null>;
}

export interface PreviewResponse {
  columns: string[];
  rows: Array<Array<string | null>>;
}

@Injectable({ providedIn: 'root' })
export class ImportsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/leads/import`;

  /** Multipart upload. Backend caps file at 10 MB and 50,000 rows. */
  upload(file: File, sourcePlatform: SourcePlatform, name?: string | null): Observable<LeadImport> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('source_platform', sourcePlatform);
    if (name) fd.append('name', name);
    return this.http.post<LeadImport>(`${this.base}/upload`, fd);
  }

  list(
    opts: {
      status?: LeadImportStatus;
      sourcePlatform?: SourcePlatform;
      page?: number;
      size?: number;
    } = {},
  ): Observable<LeadImportListResponse> {
    const params = buildHttpParams({
      status_filter: opts.status,
      source_platform: opts.sourcePlatform,
      page: opts.page,
      size: opts.size,
    });
    return this.http.get<LeadImportListResponse>(this.base, { params });
  }

  get(importId: string): Observable<LeadImport> {
    return this.http.get<LeadImport>(`${this.base}/${importId}`);
  }

  preview(importId: string, limit = 5): Observable<PreviewResponse> {
    const params = buildHttpParams({ limit });
    return this.http.get<PreviewResponse>(`${this.base}/${importId}/preview`, { params });
  }

  commit(importId: string, mapping: Record<string, string | null>): Observable<LeadImport> {
    return this.http.post<LeadImport>(`${this.base}/${importId}/commit`, {
      mapping,
    });
  }

  cancel(importId: string): Observable<LeadImport> {
    return this.http.post<LeadImport>(`${this.base}/${importId}/cancel`, {});
  }

  /** Returns a Blob so the caller can trigger a browser download. */
  downloadErrors(importId: string): Observable<Blob> {
    return this.http.get(`${this.base}/${importId}/errors.csv`, {
      responseType: 'blob',
    });
  }

  /** Returns the "duplicates skipped" CSV as a Blob for browser download. */
  downloadSkipped(importId: string): Observable<Blob> {
    return this.http.get(`${this.base}/${importId}/skipped.csv`, {
      responseType: 'blob',
    });
  }

  /** Streams the original uploaded source file as a Blob. */
  downloadSource(importId: string): Observable<Blob> {
    return this.http.get(`${this.base}/${importId}/source`, {
      responseType: 'blob',
    });
  }

  listTargets(): Observable<MappingTarget[]> {
    return this.http.get<MappingTarget[]>(`${this.base}/targets`);
  }

  listPresets(sourcePlatform: SourcePlatform): Observable<ImportPreset[]> {
    const params = buildHttpParams({ source_platform: sourcePlatform });
    return this.http.get<ImportPreset[]>(`${this.base}/presets`, { params });
  }

  createPreset(payload: PresetCreatePayload): Observable<ImportPreset> {
    return this.http.post<ImportPreset>(`${this.base}/presets`, payload);
  }

  deletePreset(presetId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/presets/${presetId}`);
  }
}
