import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams } from '../shared/services/query-builder';

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
      page: query.page,
      size: query.size,
    });
    return this.http.get<CatalogListResponse>(this.base, { params });
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
