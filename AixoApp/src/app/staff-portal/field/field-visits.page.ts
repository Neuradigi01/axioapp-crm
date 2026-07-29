import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { StaffSessionService } from '../staff-session.service';
import { extractApiError } from '@core/services/api-error.util';
import { purposeBadgeClass } from '@core/services/badge.util';
import {
  FieldVisit,
  FieldVisitCompletePayload,
} from '../../features/user/packs/furniture/field-ops/field-ops-api.service';

/**
 * Staff Portal → Field Visits tab.
 *
 * Lists visits assigned to the logged-in staff user (via the
 * `/staff-portal/me/field-visits` family, which gates on the staff
 * bearer token). Tap a visit to complete it on the spot — the
 * complete handler shares the same backend service as the admin
 * surface, including measurement copyback to any linked custom order.
 */
@Component({
  selector: 'app-field-visits-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './field-visits.page.html',
})
export class FieldVisitsPageComponent {
  protected readonly purposeBadgeClass = purposeBadgeClass;
  private readonly http = inject(HttpClient);
  private readonly session = inject(StaffSessionService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/staff-portal/me/field-visits`;

  protected readonly visits = signal<FieldVisit[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly completing = signal<string | null>(null);
  protected readonly completeError = signal<string | null>(null);

  protected readonly openCount = computed(
    () => this.visits().filter((v) => !v.completed_at).length,
  );
  protected readonly doneCount = computed(() => this.visits().filter((v) => v.completed_at).length);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this._list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.visits.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.visits.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load your visits.');
        },
      });
  }

  protected markComplete(visit: FieldVisit): void {
    if (this.completing() === visit.id) return;
    this.completing.set(visit.id);
    this.completeError.set(null);
    this._complete(visit.id, { measurements: [] })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.completing.set(null);
          this.visits.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.completing.set(null);
          this.completeError.set(extractApiError(err) ?? 'Could not mark visit complete.');
        },
      });
  }

  protected formatDateTime(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  private _list(): Observable<FieldVisit[]> {
    const params = new HttpParams().set('completed', 'false');
    return this.http.get<FieldVisit[]>(this.base, {
      params,
      headers: this._authHeaders(),
    });
  }

  private _complete(id: string, payload: FieldVisitCompletePayload): Observable<FieldVisit> {
    return this.http.post<FieldVisit>(`${this.base}/${id}/complete`, payload, {
      headers: this._authHeaders(),
    });
  }

  private _authHeaders(): HttpHeaders {
    const t = this.session.token();
    return new HttpHeaders(t ? { Authorization: `Bearer ${t}` } : {});
  }
}
