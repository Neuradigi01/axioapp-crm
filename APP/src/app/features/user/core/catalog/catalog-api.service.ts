import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams } from '../shared/services/query-builder';

/** Publish state (migration 0223). Only ``published`` items are
 *  shareable via a public URL. */
export type CatalogStatus = 'draft' | 'published' | 'unpublished' | 'archived';

export const CATALOG_STATUSES: CatalogStatus[] = ['draft', 'published', 'unpublished', 'archived'];

export interface CatalogItem {
  id: string;
  org_id: string;
  sku: string;
  name: string;
  /** C4 — long-form product notes. Nullable. */
  description: string | null;
  category: string | null;
  /** C2 — FK into the new tbl_catalog_categories table. */
  category_id: string | null;
  price: string;
  /** C6 — cost price for margin analytics. Nullable. */
  cost_price: string | null;
  currency: string;
  is_active: boolean;
  /** Publish state machine (0223). */
  status: CatalogStatus;
  published_at: string | null;
  archived_at: string | null;
  /** C13 — free-form labels. Empty array when unset. */
  tags: string[];
  image_url: string | null;
  /** C5 — gallery beyond the primary cover. Ordered. */
  image_urls: string[];
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CatalogListResponse {
  items: CatalogItem[];
  total: number;
  page: number;
  size: number;
  /** Full histogram — every CatalogStatus key present, zeros
   *  included so the tab bar renders every tab in an empty org. */
  status_counts: Record<CatalogStatus, number>;
}

/** Response for POST /catalog/{id}/public-url. `url` is deploy-agnostic
 *  (built from the request's own scheme+host on the API side); the
 *  frontend re-assembles it against `window.location.origin` for the
 *  end-user-facing copy to guarantee the URL matches whatever host the
 *  operator is actually looking at. */
export interface CatalogPublicUrl {
  url: string;
  token: string;
}

/** Anchor a server-relative `/files/...` URL to the API origin and
 *  append `?v={updated_at}` so the browser re-fetches after an image
 *  swap. The backend deliberately re-uses the same storage path per
 *  item and bumps `updated_at`; without this suffix, the cached
 *  bytes render and the operator sees the stale image on cards. */
export function buildCatalogImageHref(
  apiOrigin: string,
  url: string,
  item: Pick<CatalogItem, 'id' | 'updated_at'>,
): string {
  const stamp = item.updated_at ?? item.id;
  return `${apiOrigin}${url}?v=${encodeURIComponent(stamp)}`;
}

export interface CatalogItemCreate {
  sku: string;
  name: string;
  description?: string | null;
  category?: string | null;
  category_id?: string | null;
  price: string | number;
  cost_price?: string | number | null;
  currency?: string;
  is_active?: boolean;
  tags?: string[];
  custom_data?: Record<string, unknown>;
}

export type CatalogItemUpdate = Partial<{
  name: string;
  description: string | null;
  category: string | null;
  category_id: string | null;
  price: string | number;
  cost_price: string | number | null;
  currency: string;
  is_active: boolean;
  tags: string[];
  custom_data: Record<string, unknown>;
}>;

export interface CatalogListQuery {
  q?: string;
  category?: string;
  category_id?: string;
  active_only?: boolean;
  statuses?: CatalogStatus[];
  page?: number;
  size?: number;
}

/** C2 — first-class category entity per org. */
export interface CatalogCategory {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  description: string | null;
  icon_emoji: string | null;
  color_hex: string | null;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CatalogCategoryCreate {
  name: string;
  description?: string | null;
  icon_emoji?: string | null;
  color_hex?: string | null;
  display_order?: number;
  is_active?: boolean;
}

export type CatalogCategoryUpdate = Partial<{
  name: string;
  description: string | null;
  icon_emoji: string | null;
  color_hex: string | null;
  display_order: number;
  is_active: boolean;
}>;

/** C8 — bulk-import shapes. */
export interface CatalogBulkImportRow {
  sku: string;
  name: string;
  description?: string | null;
  category?: string | null;
  price: number | string;
  cost_price?: number | string | null;
  currency?: string;
  is_active?: boolean;
  tags?: string[];
}

export interface CatalogBulkImportRequest {
  rows: CatalogBulkImportRow[];
  dry_run: boolean;
}

export interface CatalogBulkImportRowError {
  row_index: number;
  sku: string;
  reason: string;
  /** Column whose value tripped the validator (e.g. `sku`, `name`, `currency`).
   *  `null` when the failure is row-scoped rather than field-scoped. Added
   *  when the shared per-field validators landed server-side. */
  column?: string | null;
  /** The offending value, echoed back so operators can locate it in the
   *  source file without cross-referencing. `null` when no single value
   *  applies. */
  value?: string | null;
}

export interface CatalogBulkImportResult {
  inserted: number;
  skipped: number;
  errors: CatalogBulkImportRowError[];
  dry_run: boolean;
}

@Injectable({ providedIn: 'root' })
export class CatalogApiService extends BaseCrudApiService<
  CatalogItem,
  CatalogItemCreate,
  CatalogItemUpdate
> {
  protected readonly base = `${environment.apiBaseUrl}/catalog`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/catalog_item/render`;

  list(query: CatalogListQuery = {}): Observable<CatalogListResponse> {
    const params = buildHttpParams({
      q: query.q,
      category: query.category,
      category_id: query.category_id,
      active_only: query.active_only ? query.active_only : undefined,
      statuses: query.statuses && query.statuses.length > 0 ? query.statuses : undefined,
      page: query.page,
      size: query.size,
    });
    return this.http.get<CatalogListResponse>(this.base, { params });
  }

  /** Publish → visible on the public product page + shareable URL. */
  publish(itemId: string): Observable<CatalogItem> {
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/publish`, {});
  }

  unpublish(itemId: string): Observable<CatalogItem> {
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/unpublish`, {});
  }

  archive(itemId: string): Observable<CatalogItem> {
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/archive`, {});
  }

  unarchive(itemId: string): Observable<CatalogItem> {
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/unarchive`, {});
  }

  /** Mint the shareable public URL for a published product. Returns
   *  ``{ url, token }`` — callers usually rebuild the URL from
   *  ``window.location.origin`` + token so the URL matches the host
   *  the operator is looking at (the backend can't know the FE
   *  origin when it's deployed on a different domain). */
  generatePublicUrl(itemId: string): Observable<CatalogPublicUrl> {
    return this.http.post<CatalogPublicUrl>(`${this.base}/${itemId}/public-url`, {});
  }

  /** C3 — Field defs for `entity_type='catalog_item'`. Feeds the
   *  dynamic-form renderer in the add/edit modal. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

  /** Upload (or replace) the primary cover image. Server is the source
   *  of truth on size + MIME — client-side checks are UX hints only. */
  uploadImage(itemId: string, file: File): Observable<CatalogItem> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/image`, fd);
  }

  /** Clear the primary cover image (delete the stored file too).
   *  Idempotent — returns the item unchanged if no cover was set. */
  removeImage(itemId: string): Observable<CatalogItem> {
    return this.http.delete<CatalogItem>(`${this.base}/${itemId}/image`);
  }

  /** C5 — Append a new image to the gallery. */
  addGalleryImage(itemId: string, file: File): Observable<CatalogItem> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return this.http.post<CatalogItem>(`${this.base}/${itemId}/images`, fd);
  }

  /** C5 — Remove the gallery image at `index` (0-based). */
  removeGalleryImage(itemId: string, index: number): Observable<CatalogItem> {
    const params = new HttpParams().set('index', String(index));
    return this.http.delete<CatalogItem>(`${this.base}/${itemId}/images`, { params });
  }

  /** C8 — Bulk-import rows. Set `dry_run=true` for the wizard's
   *  preview step. */
  bulkImport(payload: CatalogBulkImportRequest): Observable<CatalogBulkImportResult> {
    return this.http.post<CatalogBulkImportResult>(`${this.base}/bulk-import`, payload);
  }
}

/** C2 — Categories are their own resource under /catalog/categories. */
@Injectable({ providedIn: 'root' })
export class CatalogCategoriesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/catalog/categories`;

  list(activeOnly = false): Observable<CatalogCategory[]> {
    const params = buildHttpParams({
      active_only: activeOnly ? true : undefined,
    });
    return this.http.get<CatalogCategory[]>(this.base, { params });
  }

  create(payload: CatalogCategoryCreate): Observable<CatalogCategory> {
    return this.http.post<CatalogCategory>(this.base, payload);
  }

  update(id: string, payload: CatalogCategoryUpdate): Observable<CatalogCategory> {
    return this.http.patch<CatalogCategory>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
