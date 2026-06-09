import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { PlansResponse } from './pricing.types';

/**
 * Public plan-catalog fetch for the marketing pricing page.
 *
 * `GET /api/v1/plans` is unauthenticated by design (Step 1) — the
 * page is reachable from incognito browsers. The HTTP retry
 * interceptor (configured in `app.config.ts`) applies to this GET so
 * a transient network hiccup is invisible to the visitor.
 */
@Injectable({ providedIn: 'root' })
export class PricingApiService {
  private readonly http = inject(HttpClient);

  getPlans(): Observable<PlansResponse> {
    return this.http.get<PlansResponse>(
      `${environment.apiBaseUrl}/plans`,
    );
  }
}
