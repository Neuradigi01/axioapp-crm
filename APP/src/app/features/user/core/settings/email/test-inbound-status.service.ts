/**
 * Test-inbound status polling (tasks/email-inbound-forwarding Step 6).
 *
 * Wraps ``GET /api/v1/channel-endpoints/forwarded-address/{id}/test-inbound-status``
 * in an rxjs stream that fires every 5 seconds until either the
 * endpoint reports ``status='received'`` or the 5-minute ceiling
 * elapses. The wizard's Step-3 badge subscribes to this stream:
 *
 *   * ``kind='waiting'`` → grey badge "Waiting for test"
 *   * ``kind='received'`` → green badge "Received!" + close-wizard CTA
 *   * ``kind='timeout'`` → amber badge "Not received. Recheck settings."
 *
 * Poll cadence + ceiling are exported constants so Karma tests can
 * assert against them without hard-coding numbers in the spec.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, timer, of } from 'rxjs';
import { catchError, map, switchMap, takeWhile } from 'rxjs/operators';

import { environment } from '../../../../../../environments/environment';

export const POLL_INTERVAL_MS = 5_000;
export const POLL_CEILING_MS = 5 * 60 * 1_000;

export interface TestInboundStatus {
  status: 'waiting' | 'received';
  last_inbound_at: string | null;
}

export type PollTick =
  | { kind: 'waiting'; last_inbound_at: null }
  | { kind: 'received'; last_inbound_at: string }
  | { kind: 'timeout' };

@Injectable({ providedIn: 'root' })
export class TestInboundStatusService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/channel-endpoints/forwarded-address`;

  /** One-shot fetch. Used by the wizard on Step-3 mount before the
   * polling stream kicks in. */
  fetchOnce(endpointId: string): Observable<TestInboundStatus> {
    return this.http.get<TestInboundStatus>(`${this.base}/${endpointId}/test-inbound-status`);
  }

  /** Poll the status endpoint every :data:`POLL_INTERVAL_MS`
   * milliseconds. Completes when the endpoint reports
   * ``status='received'`` OR when :data:`POLL_CEILING_MS` elapses
   * (whichever comes first). Emits :type:`PollTick` values so
   * subscribers can render the badge state without branching on
   * the raw API shape.
   *
   * Fail-soft on HTTP errors — a transient 5xx during polling emits
   * a ``waiting`` tick rather than terminating the stream. Terminal
   * ``timeout`` fires once and completes.
   */
  poll(endpointId: string): Observable<PollTick> {
    const startedAt = Date.now();
    return timer(0, POLL_INTERVAL_MS).pipe(
      switchMap(() =>
        this.fetchOnce(endpointId).pipe(
          map((res): PollTick => {
            if (res.status === 'received') {
              return { kind: 'received', last_inbound_at: res.last_inbound_at ?? '' };
            }
            return { kind: 'waiting', last_inbound_at: null };
          }),
          catchError(() => of<PollTick>({ kind: 'waiting', last_inbound_at: null })),
        ),
      ),
      map((tick): PollTick => {
        if (tick.kind === 'received') return tick;
        if (Date.now() - startedAt >= POLL_CEILING_MS) {
          return { kind: 'timeout' };
        }
        return tick;
      }),
      // Terminate on the FIRST non-waiting tick.
      takeWhile((tick) => tick.kind === 'waiting', true),
    );
  }
}
