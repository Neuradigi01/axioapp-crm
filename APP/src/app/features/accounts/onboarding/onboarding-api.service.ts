import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { CatalogResponse } from './onboarding.types';

/**
 * Read-only catalog fetch for the onboarding picker.
 *
 * `completeOnboarding` lives on `FurnitureAuthService` so the JWT
 * rotation it performs flows through the same token-storage path as
 * `login()` and `register()`.
 */
@Injectable({ providedIn: 'root' })
export class OnboardingApiService {
  private readonly http = inject(HttpClient);

  /** Public endpoint — no auth required. Returns the ordered list of
   * tiles (real packs + "Coming soon" placeholders). */
  getCatalog(): Observable<CatalogResponse> {
    return this.http.get<CatalogResponse>(
      `${environment.apiBaseUrl}/packs/catalog`,
    );
  }
}
