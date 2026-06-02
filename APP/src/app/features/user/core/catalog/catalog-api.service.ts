import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import { buildHttpParams } from '../shared/services/query-builder';

export interface CatalogItem {
  id: string;
  org_id: string;
  sku: string;
  name: string;
  category: string | null;
  price: string;
  currency: string;
  is_active: boolean;
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
  category?: string | null;
  price: string | number;
  currency?: string;
  is_active?: boolean;
  custom_data?: Record<string, unknown>;
}

export type CatalogItemUpdate = Partial<{
  name: string;
  category: string | null;
  price: string | number;
  currency: string;
  is_active: boolean;
  custom_data: Record<string, unknown>;
}>;

export interface CatalogListQuery {
  q?: string;
  category?: string;
  active_only?: boolean;
  page?: number;
  size?: number;
}

@Injectable({ providedIn: 'root' })
export class CatalogApiService extends BaseCrudApiService<
  CatalogItem,
  CatalogItemCreate,
  CatalogItemUpdate
> {
  protected readonly base = `${environment.apiBaseUrl}/catalog`;

  list(query: CatalogListQuery = {}): Observable<CatalogListResponse> {
    const params = buildHttpParams({
      q: query.q,
      category: query.category,
      active_only: query.active_only ? query.active_only : undefined,
      page: query.page,
      size: query.size,
    });
    return this.http.get<CatalogListResponse>(this.base, { params });
  }
}
