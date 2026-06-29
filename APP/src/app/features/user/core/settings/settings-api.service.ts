import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

export interface OrgSettings {
  id: string;
  org_id: string;
  store_name: string | null;
  logo_url: string | null;
  gst_number: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  phone: string | null;
  email: string | null;
  currency: string;
  tax_rate: string;
  timezone: string;
  locale: string;
  ai_enabled: boolean;
  ai_personality: string | null;
  ai_welcome_message: string | null;
  reviews_auto_request_enabled: boolean;
  reviews_auto_request_delay_hours: number;
  // tasks/workflows Step 12 — compliance gate settings.
  quiet_hours_enabled?: boolean;
  quiet_hours_start?: string;
  quiet_hours_end?: string;
  quiet_hours_timezone?: string;
  frequency_cap_marketing_per_week?: number;
  frequency_cap_marketing_per_day?: number;
  transactional_bypass_quiet_hours?: boolean;
  transactional_bypass_frequency_cap?: boolean;
  unsubscribe_link_required_in_marketing_email?: boolean;
  created_at: string;
  updated_at: string;
}

export type OrgSettingsPatch = Partial<{
  store_name: string | null;
  logo_url: string | null;
  gst_number: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  phone: string | null;
  email: string | null;
  currency: string;
  tax_rate: string | number;
  timezone: string;
  locale: string;
  ai_enabled: boolean;
  ai_personality: string | null;
  ai_welcome_message: string | null;
  reviews_auto_request_enabled: boolean;
  reviews_auto_request_delay_hours: number;
  // tasks/workflows Step 12 — compliance gates.
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  quiet_hours_timezone: string;
  frequency_cap_marketing_per_week: number;
  frequency_cap_marketing_per_day: number;
  transactional_bypass_quiet_hours: boolean;
  transactional_bypass_frequency_cap: boolean;
  unsubscribe_link_required_in_marketing_email: boolean;
}>;

@Injectable({ providedIn: 'root' })
export class SettingsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/settings`;

  get(): Observable<OrgSettings> {
    return this.http.get<OrgSettings>(this.base);
  }

  patch(payload: OrgSettingsPatch): Observable<OrgSettings> {
    return this.http.patch<OrgSettings>(this.base, payload);
  }
}
