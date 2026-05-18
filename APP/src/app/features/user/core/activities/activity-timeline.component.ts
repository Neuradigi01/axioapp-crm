import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import {
  Activity,
  ActivityType,
  ActivitiesApiService,
} from './activities-api.service';
import { RelativeTimePipe } from './relative-time.pipe';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Reusable vertical timeline of activities for any tenant-scoped entity.
 *
 * Inputs are intentionally minimal â€” `(entityType, entityId)` only â€”
 * so this same component will back the Activities tab for Leads
 * (Step 2.12), Walk-ins, and any future entity. No knowledge of
 * "contact" lives here.
 *
 * Rows are grouped by local calendar day, latest day first.
 *
 * `reload()` is exposed so a parent (e.g. the add-note button) can
 * tell the timeline to re-pull after it adds a row optimistically.
 */
type TypeMeta = { icon: string; label: string; ringClass: string };

const TYPE_META: Record<ActivityType, TypeMeta> = {
  note: {
    icon: 'sticky-note',
    label: 'Note',
    ringClass: 'bg-amber-100 text-amber-700 ring-amber-200',
  },
  call: {
    icon: 'phone',
    label: 'Call',
    ringClass: 'bg-sky-100 text-sky-700 ring-sky-200',
  },
  email: {
    icon: 'mail',
    label: 'Email',
    ringClass: 'bg-indigo-100 text-indigo-700 ring-indigo-200',
  },
  whatsapp: {
    icon: 'message-circle',
    label: 'WhatsApp',
    ringClass: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
  },
  status_change: {
    icon: 'arrow-right',
    label: 'Status changed',
    ringClass: 'bg-violet-100 text-violet-700 ring-violet-200',
  },
  task: {
    icon: 'check',
    label: 'Task',
    ringClass: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
  },
};

interface DayGroup {
  day: string;
  label: string;
  items: Activity[];
}

@Component({
  selector: 'app-activity-timeline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RelativeTimePipe],
  templateUrl: './activity-timeline.component.html',
})
export class ActivityTimelineComponent {
  private readonly api = inject(ActivitiesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly entityType = input.required<string>();
  readonly entityId = input.required<string>();

  protected readonly items = signal<Activity[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly groups = computed<DayGroup[]>(() => {
    const buckets = new Map<string, Activity[]>();
    for (const a of this.items()) {
      const day = this.toLocalDay(a.created_at);
      const bucket = buckets.get(day);
      if (bucket) bucket.push(a);
      else buckets.set(day, [a]);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => (a < b ? 1 : a > b ? -1 : 0))
      .map(([day, items]) => ({ day, label: this.formatDayLabel(day), items }));
  });

  protected readonly skeletonRows = [0, 1, 2] as const;

  constructor() {
    effect(() => {
      const eType = this.entityType();
      const eId = this.entityId();
      if (!eType || !eId) return;
      this.reload();
    });
  }

  /** Public so a sibling component can refresh the timeline. */
  reload(): void {
    const eType = this.entityType();
    const eId = this.entityId();
    if (!eType || !eId) return;
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(eType, eId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load activities.',
          );
          this.loading.set(false);
        },
      });
  }

  /** Optimistically prepend a freshly-created activity to the list. */
  prepend(activity: Activity): void {
    this.items.update((current) => [activity, ...current]);
  }

  protected meta(type: ActivityType): TypeMeta {
    return TYPE_META[type];
  }

  protected payloadPreview(a: Activity): string {
    const payload = a.payload ?? {};
    const text = (payload as { text?: unknown }).text;
    if (typeof text === 'string' && text.length > 0) return text;
    if (a.type === 'status_change') {
      const from = (payload as { from?: unknown }).from;
      const to = (payload as { to?: unknown }).to;
      if (typeof from === 'string' && typeof to === 'string') {
        return `${from} â†’ ${to}`;
      }
    }
    // Fallback: stringify so unknown future shapes are still legible.
    try {
      return JSON.stringify(payload);
    } catch {
      return '';
    }
  }

  private toLocalDay(iso: string): string {
    // Convert to local-calendar YYYY-MM-DD so "Today" matches what the
    // user sees on their wall clock, not UTC.
    const d = new Date(iso);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private formatDayLabel(day: string): string {
    const today = this.toLocalDay(new Date().toISOString());
    if (day === today) return 'Today';
    const yest = new Date();
    yest.setDate(yest.getDate() - 1);
    if (day === this.toLocalDay(yest.toISOString())) return 'Yesterday';
    return new Date(`${day}T00:00:00`).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }

}
