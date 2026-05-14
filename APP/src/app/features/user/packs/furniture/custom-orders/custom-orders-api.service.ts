import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export interface CustomOrder {
  id: string;
  org_id: string;
  contact_id: string | null;
  lead_id: string | null;
  title: string;
  requirement: string | null;
  materials: Record<string, unknown>;
  color: string | null;
  finish: string | null;
  pipeline_stage: string;
  assigned_to_id: string | null;
  expected_delivery_date: string | null;
  total_amount: string;
  advance_paid: string;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Index signature so `CustomOrder` is structurally compatible with `PipelineItem`. */
  [key: string]: unknown;
}

export interface CustomOrderListResponse {
  items: CustomOrder[];
  total: number;
  page: number;
  size: number;
}

export interface CustomOrderCreate {
  contact_id?: string | null;
  lead_id?: string | null;
  title: string;
  requirement?: string | null;
  materials?: Record<string, unknown>;
  color?: string | null;
  finish?: string | null;
  assigned_to_id?: string | null;
  expected_delivery_date?: string | null;
  total_amount?: string | null;
  advance_paid?: string | null;
  custom_data?: Record<string, unknown>;
}

export type CustomOrderUpdate = Partial<CustomOrderCreate>;

export interface CustomOrderListQuery {
  stage?: string;
  assigned_to_id?: string;
  contact_id?: string;
  page?: number;
  size?: number;
}

export interface Measurement {
  id: string;
  org_id: string;
  order_id: string;
  item_label: string;
  length_cm: string | null;
  width_cm: string | null;
  height_cm: string | null;
  notes: string | null;
  created_at: string;
}

export interface MeasurementCreate {
  item_label: string;
  length_cm?: string | null;
  width_cm?: string | null;
  height_cm?: string | null;
  notes?: string | null;
}

export interface OrderPhoto {
  id: string;
  org_id: string;
  order_id: string;
  url: string;
  caption: string | null;
  taken_at: string | null;
  created_at: string;
}

export interface StageHistoryEntry {
  id: string;
  order_id: string;
  from_stage: string | null;
  to_stage: string;
  user_id: string | null;
  notes: string | null;
  changed_at: string;
}

@Injectable({ providedIn: 'root' })
export class CustomOrdersApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/custom-orders`;

  list(query: CustomOrderListQuery = {}): Observable<CustomOrderListResponse> {
    let params = new HttpParams();
    if (query.stage) params = params.set('stage', query.stage);
    if (query.assigned_to_id)
      params = params.set('assigned_to_id', query.assigned_to_id);
    if (query.contact_id) params = params.set('contact_id', query.contact_id);
    if (query.page) params = params.set('page', String(query.page));
    if (query.size) params = params.set('size', String(query.size));
    return this.http.get<CustomOrderListResponse>(this.base, { params });
  }

  get(id: string): Observable<CustomOrder> {
    return this.http.get<CustomOrder>(`${this.base}/${id}`);
  }

  create(payload: CustomOrderCreate): Observable<CustomOrder> {
    return this.http.post<CustomOrder>(this.base, payload);
  }

  update(id: string, payload: CustomOrderUpdate): Observable<CustomOrder> {
    return this.http.patch<CustomOrder>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  moveStage(
    id: string,
    toStage: string,
    notes?: string | null,
  ): Observable<CustomOrder> {
    return this.http.post<CustomOrder>(`${this.base}/${id}/move-stage`, {
      to_stage: toStage,
      notes: notes ?? null,
    });
  }

  listMeasurements(orderId: string): Observable<Measurement[]> {
    return this.http.get<Measurement[]>(
      `${this.base}/${orderId}/measurements`,
    );
  }

  addMeasurement(
    orderId: string,
    payload: MeasurementCreate,
  ): Observable<Measurement> {
    return this.http.post<Measurement>(
      `${this.base}/${orderId}/measurements`,
      payload,
    );
  }

  listPhotos(orderId: string): Observable<OrderPhoto[]> {
    return this.http.get<OrderPhoto[]>(`${this.base}/${orderId}/photos`);
  }

  uploadPhoto(
    orderId: string,
    file: File,
    caption: string | null,
  ): Observable<OrderPhoto> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (caption) form.append('caption', caption);
    return this.http.post<OrderPhoto>(
      `${this.base}/${orderId}/photos`,
      form,
    );
  }

  listStageHistory(orderId: string): Observable<StageHistoryEntry[]> {
    return this.http.get<StageHistoryEntry[]>(
      `${this.base}/${orderId}/stage-history`,
    );
  }
}
