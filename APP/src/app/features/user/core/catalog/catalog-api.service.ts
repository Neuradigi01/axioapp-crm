import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

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
export class CatalogApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/catalog`;

  list(query: CatalogListQuery = {}): Observable<CatalogListResponse> {
    let params = new HttpParams();
    if (query.q) params = params.set('q', query.q);
    if (query.category) params = params.set('category', query.category);
    if (query.active_only) {
      params = params.set('active_only', String(query.active_only));
    }
    if (query.page) params = params.set('page', String(query.page));
    if (query.size) params = params.set('size', String(query.size));
    return this.http.get<CatalogListResponse>(this.base, { params });
  }

  get(id: string): Observable<CatalogItem> {
    return this.http.get<CatalogItem>(`${this.base}/${id}`);
  }

  create(payload: CatalogItemCreate): Observable<CatalogItem> {
    return this.http.post<CatalogItem>(this.base, payload);
  }

  update(id: string, payload: CatalogItemUpdate): Observable<CatalogItem> {
    return this.http.patch<CatalogItem>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
