import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

/**
 * Field-type and source enums mirror the backend
 * (`src.app.core.custom_fields.models`). Keep them in sync — they're
 * what `custom-fields.page` and `field-form` render badges and pickers
 * off of, and what the API rejects unknown values for.
 */
export type FieldType =
  | 'text'
  | 'number'
  | 'select'
  | 'multiselect'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'phone'
  | 'email'
  | 'currency';

export type FieldSource = 'system' | 'pack' | 'user';

export interface CustomFieldOptions {
  choices?: string[];
  [k: string]: unknown;
}

export interface CustomField {
  id: string;
  org_id: string;
  entity_type: string;
  field_key: string;
  field_label: string;
  field_type: FieldType;
  options: CustomFieldOptions | null;
  is_required: boolean;
  is_hidden: boolean;
  display_order: number;
  source: FieldSource;
  pack_id: string | null;
  validation: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface CustomFieldCreate {
  entity_type: string;
  field_key: string;
  field_label: string;
  field_type: FieldType;
  options?: CustomFieldOptions | null;
  is_required?: boolean;
  is_hidden?: boolean;
  display_order?: number;
  validation?: Record<string, unknown> | null;
}

export interface CustomFieldUpdate {
  field_label?: string;
  is_required?: boolean;
  is_hidden?: boolean;
  display_order?: number;
  options?: CustomFieldOptions | null;
  validation?: Record<string, unknown> | null;
}

@Injectable({ providedIn: 'root' })
export class CustomFieldsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/custom-fields`;

  list(entityType: string, includeHidden = true): Observable<CustomField[]> {
    return this.http.get<CustomField[]>(this.base, {
      params: { entity_type: entityType, include_hidden: includeHidden },
    });
  }

  create(payload: CustomFieldCreate): Observable<CustomField> {
    return this.http.post<CustomField>(this.base, payload);
  }

  update(id: string, payload: CustomFieldUpdate): Observable<CustomField> {
    return this.http.patch<CustomField>(`${this.base}/${id}`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
