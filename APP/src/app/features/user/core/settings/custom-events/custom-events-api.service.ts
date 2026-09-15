import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

export type ScheduleType = 'manual' | 'date_field';
export type ScheduleSource = 'system' | 'custom';
export type RecurringMode = 'none' | 'yearly' | 'monthly';

/** Sub-payload present when `schedule_type === 'date_field'`. */
export interface ScheduleConfig {
  source: ScheduleSource;
  field_ref: string;
  offset_days: number;
  recurring: RecurringMode;
  hour_local: number;
}

/** Row from GET /custom-events/date-field-catalog. */
export interface DateFieldCatalogEntry {
  source: ScheduleSource;
  field_ref: string;
  label: string;
  group: 'System fields' | 'Custom fields';
  recurring_hint: RecurringMode;
}

/** Row projection returned by GET /custom-events. */
export interface CustomEvent {
  id: string;
  event_key: string;
  name: string;
  description: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  fires_last_30d: number;
  workflows_using_count: number;
  schedule_type: ScheduleType;
  schedule: ScheduleConfig | null;
}

/** Payload for POST /custom-events. `event_key` is immutable after
 *  creation — renaming it would silently break every workflow that
 *  subscribed. */
export interface CustomEventCreate {
  event_key: string;
  name: string;
  description?: string | null;
  schedule_type?: ScheduleType;
  schedule?: ScheduleConfig | null;
}

export interface CustomEventUpdate {
  name?: string;
  description?: string | null;
  schedule_type?: ScheduleType;
  schedule?: ScheduleConfig | null;
}

export interface CustomEventFireRequest {
  contact_id?: string | null;
  payload?: Record<string, unknown> | null;
}

export interface CustomEventFireResponse {
  occurrence_id: string;
  event_type: string;
  fired_at: string;
}

export interface CustomEventOccurrence {
  id: string;
  event_id: string;
  contact_id: string | null;
  fired_by_user_id: string | null;
  payload: Record<string, unknown>;
  fired_at: string;
}

/** Contact-timeline row — joined with the event definition so the
 *  UI renders "<name> was logged on <fired_at>" without a second
 *  round-trip. */
export interface ContactCustomEventOccurrence {
  id: string;
  event_id: string;
  event_key: string;
  event_name: string;
  fired_at: string;
  fired_by_user_id: string | null;
  payload: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class CustomEventsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/custom-events`;

  list(): Observable<CustomEvent[]> {
    return this.http.get<CustomEvent[]>(this.base);
  }

  get(id: string): Observable<CustomEvent> {
    return this.http.get<CustomEvent>(`${this.base}/${id}`);
  }

  create(payload: CustomEventCreate): Observable<CustomEvent> {
    return this.http.post<CustomEvent>(this.base, payload);
  }

  update(id: string, payload: CustomEventUpdate): Observable<CustomEvent> {
    return this.http.put<CustomEvent>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  fire(id: string, payload: CustomEventFireRequest): Observable<CustomEventFireResponse> {
    return this.http.post<CustomEventFireResponse>(`${this.base}/${id}/fire`, payload);
  }

  listOccurrences(id: string, limit = 100): Observable<CustomEventOccurrence[]> {
    return this.http.get<CustomEventOccurrence[]>(`${this.base}/${id}/occurrences`, {
      params: { limit: String(limit) },
    });
  }

  listForContact(contactId: string, limit = 50): Observable<ContactCustomEventOccurrence[]> {
    return this.http.get<ContactCustomEventOccurrence[]>(`${this.base}/by-contact/${contactId}`, {
      params: { limit: String(limit) },
    });
  }

  /** Every date/datetime field an event can subscribe to, grouped
   *  by source ('System fields' | 'Custom fields'). Feeds the
   *  create-event modal's fire-schedule picker. */
  listDateFieldCatalog(): Observable<DateFieldCatalogEntry[]> {
    return this.http.get<DateFieldCatalogEntry[]>(`${this.base}/date-field-catalog`);
  }
}
