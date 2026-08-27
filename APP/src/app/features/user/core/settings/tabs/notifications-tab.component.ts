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
import { forkJoin } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

type Channel = 'in_app' | 'email' | 'push';

interface PrefRow {
  type: string;
  channel: Channel;
  enabled: boolean;
}

/** Descriptor returned by `GET /notification-preferences/available-types`.
 *  One row per notification event surfaced in the Settings UI. Backed
 *  by `notifications/event_catalog.py` on the server — add a new entry
 *  there and it flows through here without any frontend change. */
interface AvailableType {
  event_type: string;
  label: string;
  description: string;
  group: string;
  in_app_default: boolean;
  email_default: boolean;
}

interface PrefMatrixRow {
  type: string;
  label: string;
  description: string;
  group: string;
  in_app: boolean;
  email: boolean;
  push: boolean;
}

interface PrefMatrixGroup {
  group: string;
  rows: PrefMatrixRow[];
}

/**
 * Notifications tab — per-type toggles for in-app / email / push
 * grouped by category (Appointments / Tasks / Messages / Templates).
 *
 * Types come from `GET /notification-preferences/available-types` so
 * new server-side notification events surface automatically (no
 * hardcoded map). Saved preferences from `GET /notification-preferences`
 * overlay the defaults. PATCH `/notification-preferences/{type}` writes
 * one channel toggle at a time.
 *
 * Every checkbox renders as CHECKED when no explicit preference row
 * exists — matches the backend defaults in `_channel_enabled` /
 * `_email_opted_in` (both default true as of 2026-08-26).
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

  protected readonly availableTypes = signal<AvailableType[]>([]);
  protected readonly rows = signal<PrefRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);

  /** Matrix grouped by category. Every available type appears with the
   *  backend-supplied defaults; explicit preference rows overwrite the
   *  per-channel boolean. Order inside each group follows catalog order. */
  protected readonly matrix = computed<PrefMatrixGroup[]>(() => {
    const byType = new Map<string, PrefMatrixRow>();
    for (const t of this.availableTypes()) {
      byType.set(t.event_type, {
        type: t.event_type,
        label: t.label,
        description: t.description,
        group: t.group,
        in_app: t.in_app_default,
        email: t.email_default,
        push: false,
      });
    }
    for (const r of this.rows()) {
      const row = byType.get(r.type);
      if (row) {
        row[r.channel] = r.enabled;
      }
    }
    // Group rows, preserving catalog order both across and within groups.
    const groups: PrefMatrixGroup[] = [];
    const groupIndex = new Map<string, number>();
    for (const row of byType.values()) {
      let idx = groupIndex.get(row.group);
      if (idx === undefined) {
        idx = groups.length;
        groupIndex.set(row.group, idx);
        groups.push({ group: row.group, rows: [] });
      }
      groups[idx].rows.push(row);
    }
    return groups;
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    forkJoin({
      types: this.http.get<AvailableType[]>(`${this.base}/available-types`),
      prefs: this.http.get<PrefRow[]>(this.base),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ types, prefs }) => {
          this.availableTypes.set(types);
          this.rows.set(prefs);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.availableTypes.set([]);
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
        next: (rows) => {
          // Server returns rows only for the touched `type` — merge into
          // the existing set so the other types' saved state is preserved.
          const untouched = this.rows().filter((r) => r.type !== type);
          this.rows.set([...untouched, ...rows]);
        },
        error: (err: HttpErrorResponse) =>
          this.saveError.set(extractApiError(err) ?? 'Could not save.'),
      });
  }
}
