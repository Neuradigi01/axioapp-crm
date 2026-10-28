import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

/**
 * tasks/automation-engine Step 14 — suppression list viewer.
 *
 * Shows every (channel, address, reason, created_at) row populated
 * by the bounce-handler webhooks (hard bounce / complaint /
 * unsubscribe) + the manual "block this address" action. The
 * Owner can filter by channel + reason and rehabilitate any entry
 * via the "Unsuppress" button — that removes the row so the next
 * automation run to that address proceeds normally.
 *
 * Backed by `GET /api/v1/email/suppressions` (filterable +
 * paginated) and `DELETE /api/v1/email/suppressions/{id}`. Both
 * gated on `email.accounts.manage`.
 */
interface SuppressionRow {
  id: string;
  channel: string;
  address: string;
  reason: string;
  created_at: string;
}

@Component({
  selector: 'app-email-suppression-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './suppression-list.component.html',
})
export class SuppressionListComponent {
  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/email/suppressions`;

  protected readonly rows = signal<SuppressionRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly removingId = signal<string | null>(null);

  protected readonly form = this.fb.group({
    channel: this.fb.control<string>('', { nonNullable: true }),
    reason: this.fb.control<string>('', { nonNullable: true }),
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.error.set(null);
    let params = new HttpParams().set('limit', '200');
    const ch = this.form.controls.channel.value;
    const rs = this.form.controls.reason.value;
    if (ch) params = params.set('channel', ch);
    if (rs) params = params.set('reason', rs);

    this._list(params)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rs) => {
          this.rows.set(rs);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load.');
        },
      });
  }

  protected unsuppress(row: SuppressionRow): void {
    this.removingId.set(row.id);
    this._delete(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.rows.update((current) => current.filter((r) => r.id !== row.id));
          this.removingId.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.removingId.set(null);
          this.error.set(extractApiError(err) ?? 'Could not unsuppress.');
        },
      });
  }

  protected reasonBadgeClass(reason: string): string {
    switch (reason) {
      case 'hard_bounce':
        return 'bg-rose-100 text-rose-800 border-rose-200';
      case 'complaint':
        return 'bg-amber-100 text-amber-800 border-amber-200';
      case 'unsubscribe':
        return 'bg-zinc-100 text-zinc-700 border-zinc-200';
      case 'manual':
        return 'bg-indigo-100 text-indigo-800 border-indigo-200';
      default:
        return 'bg-zinc-100 text-zinc-700 border-zinc-200';
    }
  }

  private _list(params: HttpParams): Observable<SuppressionRow[]> {
    return this.http.get<SuppressionRow[]>(this.base, { params });
  }

  private _delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
