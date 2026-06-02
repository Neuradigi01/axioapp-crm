import { HttpClient } from '@angular/common/http';
import { inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Base class for Angular "standard CRUD" services. Consolidates the
 * four byte-identical methods every entity service used to redeclare:
 *
 *     get(id) → GET    {base}/{id}     → Observable<T>
 *     create(payload) → POST   {base}             → Observable<T>
 *     update(id, payload) → PATCH  {base}/{id}     → Observable<T>
 *     delete(id) → DELETE {base}/{id}     → Observable<void>
 *
 * Subclass with concrete types + a `base` URL. The subclass owns
 * `list()` (envelope shapes vary per entity — paginated vs cursor vs
 * bare array), bulk methods (entity-specific bodies / result types),
 * and any domain-specific methods.
 *
 * @example
 *   @Injectable({ providedIn: 'root' })
 *   export class ContactsApiService extends BaseCrudApiService<
 *     Contact, ContactCreate, ContactUpdate
 *   > {
 *     protected readonly base = `${environment.apiBaseUrl}/contacts`;
 *     list(query): Observable<ContactListResponse> { ... }
 *     bulkReassign(ids, body): Observable<{reassigned: number}> { ... }
 *   }
 */
export abstract class BaseCrudApiService<
  T,
  TCreate = Partial<T>,
  TUpdate = Partial<T>,
> {
  protected readonly http = inject(HttpClient);

  /** Fully-qualified base URL for the entity, e.g.
   * ``${environment.apiBaseUrl}/contacts``. */
  protected abstract readonly base: string;

  get(id: string): Observable<T> {
    return this.http.get<T>(`${this.base}/${id}`);
  }

  create(payload: TCreate): Observable<T> {
    return this.http.post<T>(this.base, payload);
  }

  update(id: string, payload: TUpdate): Observable<T> {
    return this.http.patch<T>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
