import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type BlockReason = 'spam' | 'fraud' | 'requested' | 'harassment' | 'other';

export interface BlockedNumber {
  id: string;
  phone_number: string;
  reason: BlockReason;
  blocked_by_user_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface BlockListPage {
  items: BlockedNumber[];
  total: number;
  page: number;
  size: number;
}

export interface BlockNumberRequest {
  phone_number: string;
  reason: BlockReason;
  notes?: string | null;
}

/**
 * Block-list API service (whatsapp-platform-upgrade Step 23).
 * Gated on `whatsapp.opt_in.manage` server-side; the page itself
 * is route-guarded on the same key so junior staff never see the
 * surface.
 */
@Injectable({ providedIn: 'root' })
export class BlockListService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/block-list`;

  list(
    search?: string,
    page = 1,
    size = 50,
  ): Observable<BlockListPage> {
    let params = new HttpParams().set('page', page).set('size', size);
    if (search) params = params.set('search', search);
    return this.http.get<BlockListPage>(this.base, { params });
  }

  add(body: BlockNumberRequest): Observable<BlockedNumber> {
    return this.http.post<BlockedNumber>(this.base, body);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
