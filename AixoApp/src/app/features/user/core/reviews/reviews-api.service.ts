import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

export type ReviewStatus = 'pending_reply' | 'replied' | 'escalated';

export interface Review {
  id: string;
  org_id: string;
  source: string;
  source_id: string | null;
  contact_id: string | null;
  rating: number;
  text: string | null;
  reply_text: string | null;
  replied_at: string | null;
  replied_by_id: string | null;
  status: ReviewStatus;
  tags: string[];
  created_at: string;
}

export interface ReviewListResponse {
  items: Review[];
  total: number;
  page: number;
  size: number;
}

export interface ReviewListQuery {
  source?: string;
  rating?: number;
  status?: ReviewStatus;
  page?: number;
  size?: number;
}

export interface RatingDistributionRow {
  rating: number;
  count: number;
}

export interface ReviewStats {
  total: number;
  average_rating: number;
  response_rate_pct: number;
  distribution: RatingDistributionRow[];
  pending_count: number;
  alerts_last_7_days: number;
}

@Injectable({ providedIn: 'root' })
export class ReviewsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/reviews`;

  list(query: ReviewListQuery = {}): Observable<ReviewListResponse> {
    const params = buildHttpParams({
      source: query.source,
      rating: query.rating ? query.rating : undefined,
      status: query.status,
      page: query.page,
      size: query.size,
    });
    return this.http.get<ReviewListResponse>(this.base, { params });
  }

  stats(): Observable<ReviewStats> {
    return this.http.get<ReviewStats>(`${this.base}/stats`);
  }

  reply(id: string, text: string): Observable<Review> {
    return this.http.post<Review>(`${this.base}/${id}/reply`, { text });
  }

  escalate(id: string, reason?: string): Observable<Review> {
    return this.http.post<Review>(`${this.base}/${id}/escalate`, {
      reason: reason ?? null,
    });
  }
}
