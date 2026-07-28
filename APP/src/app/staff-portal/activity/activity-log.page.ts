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

import { RelativeTimePipe } from '../../features/user/core/activities/relative-time.pipe';
import { extractApiError } from '@core/services/api-error.util';
import { StaffActivity, StaffPortalApiService } from '../staff-portal-api.service';

interface DayGroup {
  dayKey: string;
  dayLabel: string;
  items: StaffActivity[];
}

const TYPE_LABEL: Record<string, string> = {
  note: 'Note',
  call: 'Call',
  email: 'Email',
  whatsapp: 'WhatsApp',
  status_change: 'Status change',
  task: 'Task',
};

/**
 * My Activity Log — the same stream the admin sees on the staff-tab
 * activity view, but scoped to "me" via `GET /staff-portal/me/activity`.
 */
@Component({
  selector: 'app-staff-portal-activity-log-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RelativeTimePipe],
  templateUrl: './activity-log.page.html',
})
export class StaffPortalActivityLogPageComponent {
  private readonly api = inject(StaffPortalApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<StaffActivity[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly groups = computed<DayGroup[]>(() => {
    const byKey = new Map<string, DayGroup>();
    for (const item of this.items()) {
      const d = new Date(item.created_at);
      const key = d.toISOString().slice(0, 10);
      let g = byKey.get(key);
      if (!g) {
        g = { dayKey: key, dayLabel: this._dayLabel(d), items: [] };
        byKey.set(key, g);
      }
      g.items.push(item);
    }
    return [...byKey.values()].sort((a, b) => b.dayKey.localeCompare(a.dayKey));
  });

  constructor() {
    this.reload();
  }

  protected typeLabel(t: string): string {
    return TYPE_LABEL[t] ?? 'Activity';
  }

  protected snippet(a: StaffActivity): string {
    const text = (a.payload as { text?: unknown })?.text;
    if (typeof text === 'string' && text.length > 0) return text;
    return this.typeLabel(a.type);
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .activity(100)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.items.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load activity.');
        },
      });
  }

  private _dayLabel(d: Date): string {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const dd = new Date(d);
    dd.setHours(0, 0, 0, 0);
    const diff = Math.round((today.getTime() - dd.getTime()) / 86_400_000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    return d.toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }
}
