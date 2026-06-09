import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { SubscriptionCurrent } from '../types/subscription.types';

/**
 * Thin wrapper over the authenticated billing endpoints.
 *
 * Step 15 only consumes `GET /subscriptions/current`. Steps 16 / 17 /
 * 20 will add `change`, `cancel`, `seats`, `checkout`, and the
 * invoice list — all live on this service so the HTTP interceptors
 * (auth, retry) apply uniformly.
 */
@Injectable({ providedIn: 'root' })
export class BillingApiService {
  private readonly http = inject(HttpClient);

  getCurrent(): Observable<SubscriptionCurrent> {
    return this.http.get<SubscriptionCurrent>(
      `${environment.apiBaseUrl}/subscriptions/current`,
    );
  }
}
