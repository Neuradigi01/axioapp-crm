import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../../core/shared/services/query-builder';

export type MovementType = 'receipt' | 'dispatch' | 'adjust' | 'transfer';
export type AlertSeverity = 'low' | 'out';
export type AlertPriority = 'low' | 'med' | 'high';
export type AlertStatus = 'open' | 'ordered' | 'closed';

export interface Warehouse {
  id: string;
  org_id: string;
  name: string;
  address: string | null;
  contact_phone: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface InventoryItem {
  id: string;
  org_id: string;
  catalog_item_id: string | null;
  warehouse_id: string;
  sku: string;
  material: string | null;
  color: string | null;
  finish: string | null;
  dimensions: Record<string, unknown>;
  qty_on_hand: number;
  qty_reserved: number;
  reorder_level: number;
  last_received_at: string | null;
  custom_data: Record<string, unknown>;
  cover_url: string | null;
  is_best_seller: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface InventoryItemFullCreate {
  name: string;
  category?: string | null;
  price?: number | string;
  description?: string | null;
  warehouse_id: string;
  sku: string;
  material?: string | null;
  color?: string | null;
  finish?: string | null;
  dimensions?: Record<string, unknown>;
  reorder_level?: number;
  is_best_seller?: boolean;
  is_active?: boolean;
}

export interface CoverUploadResponse {
  cover_url: string;
}

export interface InventoryItemListResponse {
  items: InventoryItem[];
  total: number;
  page: number;
  size: number;
}

export interface InventoryItemQuery {
  warehouse_id?: string;
  category?: string;
  q?: string;
  active_only?: boolean;
  page?: number;
  size?: number;
}

export interface MovementCreate {
  type: MovementType;
  qty: number;
  reference_type?: string | null;
  reference_id?: string | null;
  notes?: string | null;
}

export interface Movement {
  id: string;
  org_id: string;
  item_id: string;
  type: MovementType;
  qty: number;
  reference_type: string | null;
  reference_id: string | null;
  notes: string | null;
  user_id: string | null;
  created_at: string;
}

export interface StockAlert {
  id: string;
  org_id: string;
  item_id: string;
  severity: AlertSeverity;
  priority: AlertPriority;
  suggested_reorder_qty: number;
  status: AlertStatus;
  created_at: string;
  closed_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class InventoryApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/inventory`;

  // --- Warehouses ---
  listWarehouses(): Observable<Warehouse[]> {
    return this.http.get<Warehouse[]>(`${this.base}/warehouses`);
  }

  // --- Items ---
  listItems(query: InventoryItemQuery = {}): Observable<InventoryItemListResponse> {
    const params = buildHttpParams({
      warehouse_id: query.warehouse_id,
      category: query.category,
      q: query.q,
      active_only: query.active_only ? true : undefined,
      page: query.page,
      size: query.size,
    });
    return this.http.get<InventoryItemListResponse>(`${this.base}/items`, { params });
  }

  getItem(id: string): Observable<InventoryItem> {
    return this.http.get<InventoryItem>(`${this.base}/items/${id}`);
  }

  /** Atomic create: a catalog row + an inventory row in one transaction. */
  createItemFull(payload: InventoryItemFullCreate): Observable<InventoryItem> {
    return this.http.post<InventoryItem>(`${this.base}/items/full`, payload);
  }

  /** Upload the cover image. Backend stores via `LocalStorage`. */
  uploadCover(itemId: string, file: File): Observable<CoverUploadResponse> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<CoverUploadResponse>(`${this.base}/items/${itemId}/cover`, form);
  }

  // --- Movements ---
  listMovements(itemId: string, limit = 100): Observable<Movement[]> {
    const params = buildHttpParams({ limit });
    return this.http.get<Movement[]>(`${this.base}/items/${itemId}/movements`, { params });
  }

  recordMovement(itemId: string, payload: MovementCreate): Observable<Movement> {
    return this.http.post<Movement>(`${this.base}/items/${itemId}/movements`, payload);
  }

  // --- Alerts ---
  listAlerts(
    opts: { severity?: AlertSeverity; status?: AlertStatus } = {},
  ): Observable<StockAlert[]> {
    const params = buildHttpParams({
      severity: opts.severity,
      status: opts.status,
    });
    return this.http.get<StockAlert[]>(`${this.base}/alerts`, { params });
  }

  updateAlertStatus(id: string, newStatus: AlertStatus): Observable<StockAlert> {
    return this.http.patch<StockAlert>(`${this.base}/alerts/${id}`, {
      status: newStatus,
    });
  }
}
