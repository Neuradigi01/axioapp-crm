import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import type {
  Property,
  PropertyCreate,
  PropertyImage,
  PropertyListFilters,
  PropertyListResponse,
  PropertyUpdate,
  PublicUrlResponse,
} from './property.types';

/**
 * HTTP client for the Property module.
 *
 * Endpoints:
 *   - `GET    /property`                          list + status_counts
 *   - `GET    /property/{id}`                     detail
 *   - `POST   /property`                          create (Step 7)
 *   - `PATCH  /property/{id}`                     partial update (Step 7)
 *   - `DELETE /property/{id}`                     hard delete (Step 8)
 *   - `POST   /property/{id}/publish`             lifecycle (Step 8)
 *   - `POST   /property/{id}/unpublish`
 *   - `POST   /property/{id}/archive`
 *   - `POST   /property/{id}/unarchive`
 *   - `POST   /property/{id}/mark-sold`
 *   - `POST   /property/{id}/public-url`          Step 8 copy-link flow
 *   - `POST   /property/{id}/images` + friends    Step 7 gallery
 */
@Injectable({ providedIn: 'root' })
export class PropertyApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/property`;

  list(
    filters: PropertyListFilters = {},
    page = 1,
    pageSize = 20,
  ): Observable<PropertyListResponse> {
    let params = new HttpParams().set('page', page).set('page_size', pageSize);
    if (filters.statuses?.length) {
      for (const s of filters.statuses) params = params.append('statuses', s);
    }
    if (filters.property_type) params = params.set('property_type', filters.property_type);
    if (filters.category) params = params.set('category', filters.category);
    if (filters.city) params = params.set('city', filters.city);
    if (filters.search) params = params.set('search', filters.search);
    if (filters.owner_id) params = params.set('owner_id', filters.owner_id);
    if (filters.min_price !== undefined) params = params.set('min_price', filters.min_price);
    if (filters.max_price !== undefined) params = params.set('max_price', filters.max_price);
    if (filters.sort_by) params = params.set('sort_by', filters.sort_by);
    if (filters.sort_desc !== undefined) params = params.set('sort_desc', filters.sort_desc);
    return this.http.get<PropertyListResponse>(this.base, { params });
  }

  getById(id: string): Observable<Property> {
    return this.http.get<Property>(`${this.base}/${id}`);
  }

  create(payload: PropertyCreate): Observable<Property> {
    return this.http.post<Property>(this.base, payload);
  }

  update(id: string, payload: PropertyUpdate): Observable<Property> {
    return this.http.patch<Property>(`${this.base}/${id}`, payload);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  publish(id: string): Observable<Property> {
    return this.http.post<Property>(`${this.base}/${id}/publish`, {});
  }

  unpublish(id: string): Observable<Property> {
    return this.http.post<Property>(`${this.base}/${id}/unpublish`, {});
  }

  archive(id: string): Observable<Property> {
    return this.http.post<Property>(`${this.base}/${id}/archive`, {});
  }

  unarchive(id: string): Observable<Property> {
    return this.http.post<Property>(`${this.base}/${id}/unarchive`, {});
  }

  markSold(id: string): Observable<Property> {
    return this.http.post<Property>(`${this.base}/${id}/mark-sold`, {});
  }

  generatePublicUrl(id: string): Observable<PublicUrlResponse> {
    return this.http.post<PublicUrlResponse>(`${this.base}/${id}/public-url`, {});
  }

  /** Mint the shareable whole-org listings URL — one link that opens
   *  the public grid of every published property for the caller's
   *  org. Always succeeds (unlike ``generatePublicUrl``, which
   *  requires the property to be published). */
  generateStorePublicUrl(): Observable<PublicUrlResponse> {
    return this.http.post<PublicUrlResponse>(`${this.base}/store/public-url`, {});
  }

  // ---------------------------------------------------------------------
  // Gallery — multipart upload, delete, reorder, set featured.
  // ---------------------------------------------------------------------

  uploadImages(id: string, files: File[]): Observable<PropertyImage[]> {
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    return this.http.post<PropertyImage[]>(`${this.base}/${id}/images`, form);
  }

  deleteImage(id: string, imageId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/images/${imageId}`);
  }

  reorderImages(id: string, imageIds: string[]): Observable<PropertyImage[]> {
    return this.http.patch<PropertyImage[]>(`${this.base}/${id}/images/reorder`, {
      image_ids: imageIds,
    });
  }

  setFeaturedImage(id: string, imageId: string): Observable<PropertyImage> {
    return this.http.patch<PropertyImage>(`${this.base}/${id}/images/${imageId}/featured`, {});
  }
}
