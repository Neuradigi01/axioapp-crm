import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';

import { environment } from '../../../../../../environments/environment';

type Channel = 'in_app' | 'email' | 'push';

interface PrefRow {
  type: string;
  channel: Channel;
  enabled: boolean;
}

interface PrefMatrixRow {
  type: string;
  in_app: boolean;
  email: boolean;
  push: boolean;
}

/**
 * Notifications tab — per-type toggles for in-app / email / push.
 * Reads + writes the existing `/api/v1/notification-preferences`
 * endpoints from Step 2.15. Types are free-form; the table grows as
 * other modules emit new notification types.
 */
@Component({
  selector: 'app-settings-notifications-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './notifications-tab.component.html',
})
export class NotificationsTabComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = `${environment.apiBaseUrl}/notification-preferences`;

  protected readonly rows = signal<PrefRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);

  protected readonly matrix = computed<PrefMatrixRow[]>(() => {
    const byType = new Map<string, PrefMatrixRow>();
    for (const r of this.rows()) {
      let row = byType.get(r.type);
      if (!row) {
        row = { type: r.type, in_app: true, email: true, push: true };
        byType.set(r.type, row);
      }
      row[r.channel] = r.enabled;
    }
    return [...byType.values()].sort((a, b) => a.type.localeCompare(b.type));
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.http
      .get<PrefRow[]>(this.base)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.rows.set([]);
          this.loading.set(false);
          this.loadError.set(this._extract(err) ?? 'Could not load.');
        },
      });
  }

  protected toggle(type: string, channel: Channel, current: boolean): void {
    const next = !current;
    this.saveError.set(null);
    this.http
      .patch<PrefRow[]>(`${this.base}/${encodeURIComponent(type)}`, {
        [channel]: next,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.rows.set(rows),
        error: (err: HttpErrorResponse) =>
          this.saveError.set(this._extract(err) ?? 'Could not save.'),
      });
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
