import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';

/**
 * Wire shapes for the public catalog endpoints. Both intentionally
 * omit every internal UUID (`id`, `org_id`) — the Fernet token in
 * the URL is the only stable identifier a visitor should ever see.
 */
export interface PublicCatalogCard {
  name: string;
  sku: string;
  category: string | null;
  price: string | number;
  currency: string;
  short_description: string | null;
  tags: string[];
  image_url: string | null;
  /** Path only — the backend returns `/product/{token}`. */
  public_url: string;
}

export interface PublicCatalogDetail {
  name: string;
  sku: string;
  description: string | null;
  category: string | null;
  price: string | number;
  currency: string;
  tags: string[];
  image_url: string | null;
  image_urls: string[];
}

/** Wire shape for `GET /api/public/store/{token}` — the whole-org
 *  storefront view. Wraps grid cards with the org's display name so
 *  the page hero can render "<Org Name>" without a second lookup. */
export interface PublicStore {
  org_name: string;
  items: PublicCatalogCard[];
}

/**
 * HTTP client for the public catalog endpoints (`/api/public/*`).
 *
 * These requests hit a different URL prefix from the authenticated
 * API surface (`/api/v1/*`), so the app-wide `jwtInterceptor` does
 * NOT attach a Bearer token to them (its `ownsRequest` check
 * whitelists `/api/v1` only).
 */
@Injectable({ providedIn: 'root' })
export class PublicCatalogApiService {
  private readonly http = inject(HttpClient);
  /** Public prefix derived from the authenticated base — same host,
   *  different path. */
  private readonly base = environment.apiBaseUrl.replace(/\/api\/v\d+\/?$/, '/api/public');

  listPublic(orgSlug: string): Observable<PublicCatalogCard[]> {
    const params = new HttpParams().set('org', orgSlug);
    return this.http.get<PublicCatalogCard[]>(`${this.base}/catalog`, { params });
  }

  getByToken(token: string): Observable<PublicCatalogDetail> {
    return this.http.get<PublicCatalogDetail>(`${this.base}/catalog/${token}`);
  }

  /** Fetch the whole-org storefront by its Fernet token — one call
   *  returns the org name + every currently-published item. */
  getStoreByToken(token: string): Observable<PublicStore> {
    return this.http.get<PublicStore>(`${this.base}/store/${token}`);
  }
}
