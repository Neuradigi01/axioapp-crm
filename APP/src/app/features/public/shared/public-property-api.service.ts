import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';

/**
 * Wire shapes for the two public endpoints. Both intentionally omit
 * every internal UUID (`id`, `org_id`, `owner_id`, `property_id`) —
 * the Fernet token in the URL is the only stable identifier a
 * visitor should ever see.
 */
export interface PublicPropertyCard {
  title: string;
  property_type: string;
  category: string;
  price: string | number | null;
  currency: string;
  city: string | null;
  state: string | null;
  short_description: string | null;
  featured_image_url: string | null;
  /** Path only — the backend returns `/property/{token}`. */
  public_url: string;
}

export interface PublicPropertyImage {
  image_url: string | null;
  display_order: number;
  is_featured: boolean;
}

export interface PublicPropertyDetail {
  title: string;
  description: string | null;
  property_type: string;
  category: string;
  price: string | number | null;
  currency: string;
  address_line: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  pincode: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  area_value: string | number | null;
  area_unit: string | null;
  amenities: string[];
  contact_person: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  images: PublicPropertyImage[];
  featured_image_url: string | null;
}

/**
 * HTTP client for the public property endpoints (`/api/public/*`).
 *
 * These requests hit a different URL prefix from the authenticated
 * API surface (`/api/v1/*`), so the app-wide `jwtInterceptor` does
 * NOT attach a Bearer token to them (its `ownsRequest` check
 * whitelists `/api/v1` only). Nothing to opt-out of on this side.
 */
@Injectable({ providedIn: 'root' })
export class PublicPropertyApiService {
  private readonly http = inject(HttpClient);
  /** Public prefix derived from the authenticated base — same host,
   * different path. Handles both the dev `/api/v1` and any future
   * versioned base like `/api/v2` cleanly. */
  private readonly base = environment.apiBaseUrl.replace(/\/api\/v\d+\/?$/, '/api/public');

  listPublic(orgSlug: string): Observable<PublicPropertyCard[]> {
    const params = new HttpParams().set('org', orgSlug);
    return this.http.get<PublicPropertyCard[]>(`${this.base}/properties`, { params });
  }

  getByToken(token: string): Observable<PublicPropertyDetail> {
    return this.http.get<PublicPropertyDetail>(`${this.base}/property/${token}`);
  }
}
