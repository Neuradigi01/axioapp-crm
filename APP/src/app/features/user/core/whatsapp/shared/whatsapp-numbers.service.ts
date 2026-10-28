import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, of, tap } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/**
 * Slim shape returned by `GET /integrations/whatsapp/numbers` (Step 27a).
 * The SPA reuses this for every multi-number picker: chat-thread
 * "Send from", campaign create modal, Settings integrations card,
 * business-profile tabs, phone-health side-by-side.
 */
export interface WhatsAppNumber {
  phone_id: string;
  display_phone_number: string;
  verified_name: string | null;
  waba_id: string;
  is_default: boolean;
  messaging_limit_tier: string | null;
  quality_rating: string | null;
}

/**
 * Multi-number registry for the SPA (Step 27b).
 *
 * Caches the result in-memory so the composer and other pickers
 * that mount per-conversation don't refetch on every navigation.
 * Components that need fresh data call `refresh()`; mutations on
 * the Settings page also call `refresh()` after connect / disconnect
 * so the dropdowns pick up the new state.
 *
 * The cache is *process-local to the SPA tab* — a connect from a
 * different operator's session won't invalidate this one until the
 * next page refresh, but the worst case is "operator sees the
 * picker without the new phone for a few seconds" which is
 * acceptable for an inherently low-churn surface.
 */
@Injectable({ providedIn: 'root' })
export class WhatsAppNumbersService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/integrations/whatsapp/numbers`;

  /** Cached list — empty until first fetch + null sentinel for
   *  "haven't tried yet" so consumers can distinguish "loading"
   *  from "loaded but empty". */
  readonly numbers = signal<WhatsAppNumber[] | null>(null);

  /** True when at least 2 phones are connected — the convention every
   *  picker uses to decide "show dropdown" vs "single-number org,
   *  hide picker entirely". */
  readonly isMulti = (): boolean => (this.numbers()?.length ?? 0) >= 2;

  /** Default phone id for fallback — `null` when the org has zero
   *  connected phones. */
  readonly defaultPhoneId = (): string | null => {
    const list = this.numbers() ?? [];
    return (list.find((n) => n.is_default) ?? list[0])?.phone_id ?? null;
  };

  /** Fetch unless we already have a cached list. Components in a
   *  loop (composer mounts per conversation) call this; only the
   *  first one in a session hits the wire. */
  ensureLoaded(): Observable<WhatsAppNumber[]> {
    const cached = this.numbers();
    if (cached !== null) {
      return of(cached);
    }
    return this.refresh();
  }

  /** Force a refetch — invoked after connect / disconnect on the
   *  Settings card so the dropdowns light up the new state. */
  refresh(): Observable<WhatsAppNumber[]> {
    return this.http.get<WhatsAppNumber[]>(this.base).pipe(tap((list) => this.numbers.set(list)));
  }
}
