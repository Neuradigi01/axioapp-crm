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
import { extractApiError } from '@core/services/api-error.util';

type Channel = 'in_app' | 'email' | 'push';

interface PrefRow {
  type: string;
  channel: Channel;
  enabled: boolean;
}

interface PrefMatrixRow {
  type: string;
  label: string;
  in_app: boolean;
  email: boolean;
  push: boolean;
}

/**
 * Display labels for known notification types. Unknown types fall back
 * to the raw key so a new module-emitted type isn't invisible until we
 * remember to add a label.
 */
const TYPE_LABELS: Readonly<Record<string, string>> = {
  'appointment.assigned': 'New appointment assigned to me',
  'appointment.rescheduled': 'Appointment I own was rescheduled',
  'appointment.cancelled': 'Appointment I own was cancelled',
};

/**
 * Notifications tab â€” per-type toggles for in-app / email / push.
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

  /**
   * Known appointment.* types are surfaced even when the user has no
   * preference rows yet (default in-app ON, email OFF). The matrix
   * therefore always renders the three appointment rows + whatever
   * other types the backend has emitted for this user.
   */
  protected readonly matrix = computed<PrefMatrixRow[]>(() => {
    const byType = new Map<string, PrefMatrixRow>();
    for (const t of Object.keys(TYPE_LABELS)) {
      byType.set(t, {
        type: t,
        label: TYPE_LABELS[t],
        in_app: true,
        email: false,
        push: false,
      });
    }
    for (const r of this.rows()) {
      let row = byType.get(r.type);
      if (!row) {
        row = {
          type: r.type,
          label: TYPE_LABELS[r.type] ?? r.type,
          in_app: true,
          email: false,
          push: false,
        };
        byType.set(r.type, row);
      }
      row[r.channel] = r.enabled;
    }
    return [...byType.values()].sort((a, b) => a.label.localeCompare(b.label));
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
          this.loadError.set(extractApiError(err) ?? 'Could not load.');
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
          this.saveError.set(extractApiError(err) ?? 'Could not save.'),
      });
  }
}
