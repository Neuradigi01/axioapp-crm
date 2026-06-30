import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/**
 * WhatsApp Business profile API client
 * (whatsapp-platform-upgrade Step 11).
 *
 * Mirrors the Step-11 backend at
 * `/api/v1/integrations/whatsapp/business-profile`.
 */

export type WhatsAppBusinessVertical =
  | 'UNDEFINED'
  | 'OTHER'
  | 'AUTO'
  | 'BEAUTY'
  | 'APPAREL'
  | 'EDU'
  | 'ENTERTAIN'
  | 'EVENT_PLAN'
  | 'FINANCE'
  | 'GROCERY'
  | 'GOVT'
  | 'HOTEL'
  | 'HEALTH'
  | 'NONPROFIT'
  | 'PROF_SERVICES'
  | 'RETAIL'
  | 'TRAVEL'
  | 'RESTAURANT';

export interface BusinessHoursInterval {
  open: string;
  close: string;
}

export interface BusinessHoursDay {
  day: number; // 0..6, Monday..Sunday (ISO)
  intervals: BusinessHoursInterval[];
}

export interface WhatsAppBusinessProfile {
  phone_id: string;
  display_phone_number: string;
  verified_name: string | null;
  about: string | null;
  description: string | null;
  address: string | null;
  email: string | null;
  websites: string[];
  vertical: string | null;
  profile_picture_url: string | null;
  last_synced_at: string | null;
  business_hours: BusinessHoursDay[];
  greeting_message: string | null;
  away_message: string | null;
}

export interface WhatsAppBusinessProfilePatch {
  about?: string | null;
  description?: string | null;
  address?: string | null;
  email?: string | null;
  websites?: string[];
  vertical?: WhatsAppBusinessVertical;
  business_hours?: BusinessHoursDay[];
  greeting_message?: string | null;
  away_message?: string | null;
}

/**
 * Step 16 — auto-reply pipeline settings.
 *
 * Subset of the same `WhatsAppAccountConfig` row the business
 * profile editor reads; lives on a dedicated endpoint so the
 * auto-reply section can fetch / save without re-uploading the
 * whole profile.
 */
export interface AutoReplySettings {
  greeting_enabled: boolean;
  greeting_message: string | null;
  greeting_template_id: string | null;

  away_enabled: boolean;
  away_message: string | null;
  away_template_id: string | null;

  business_hours: BusinessHoursDay[];
}

export interface AutoReplySettingsPatch {
  greeting_enabled?: boolean;
  greeting_message?: string | null;
  greeting_template_id?: string | null;
  away_enabled?: boolean;
  away_message?: string | null;
  away_template_id?: string | null;
}

@Injectable({ providedIn: 'root' })
export class WhatsAppBusinessProfileApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/business-profile`;
  private readonly autoReplyBase = `${environment.apiBaseUrl}/integrations/whatsapp/auto-reply`;

  get(): Observable<WhatsAppBusinessProfile> {
    return this.http.get<WhatsAppBusinessProfile>(this.base);
  }

  patch(payload: WhatsAppBusinessProfilePatch): Observable<WhatsAppBusinessProfile> {
    return this.http.patch<WhatsAppBusinessProfile>(this.base, payload);
  }

  /** Pull current Meta-side values + persist to the local mirror.
   *  Stamps `last_synced_at`. */
  refresh(): Observable<WhatsAppBusinessProfile> {
    return this.http.post<WhatsAppBusinessProfile>(`${this.base}/refresh`, {});
  }

  /** Upload a square JPEG/PNG profile picture (≤ 5 MB). The new
   *  public URL lands on the next refresh which the backend triggers
   *  for us; the returned row reflects that. */
  uploadPicture(file: File): Observable<WhatsAppBusinessProfile> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<WhatsAppBusinessProfile>(`${this.base}/picture`, form);
  }

  // --- Auto-reply (whatsapp-platform-upgrade Step 16) -----------------

  /** Read the auto-reply toggles + linked template references. */
  getAutoReplySettings(): Observable<AutoReplySettings> {
    return this.http.get<AutoReplySettings>(`${this.autoReplyBase}/settings`);
  }

  /** Update the auto-reply toggles + linked templates. Server
   *  refuses to save an enabled toggle without a body OR template. */
  patchAutoReplySettings(payload: AutoReplySettingsPatch): Observable<AutoReplySettings> {
    return this.http.patch<AutoReplySettings>(`${this.autoReplyBase}/settings`, payload);
  }
}
