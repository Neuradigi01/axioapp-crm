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

import { RelativeTimePipe } from '../../activities/relative-time.pipe';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import type { LucideIconName } from '../../shared/icons';
import { extractApiError } from '@core/services/api-error.util';
import { StaffActivity, StaffApiService, StaffWithPerformance } from '../staff-api.service';

interface TypeMeta {
  icon: LucideIconName;
  label: string;
  ring: string;
}

const TYPE_META: Record<string, TypeMeta> = {
  note: {
    icon: 'sticky-note',
    label: 'Note',
    ring: 'bg-amber-100 text-amber-700 ring-amber-200',
  },
  call: {
    icon: 'phone',
    label: 'Call',
    ring: 'bg-sky-100 text-sky-700 ring-sky-200',
  },
  email: {
    icon: 'mail',
    label: 'Email',
    ring: 'bg-violet-100 text-violet-700 ring-violet-200',
  },
  whatsapp: {
    icon: 'message-circle',
    label: 'WhatsApp',
    ring: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
  },
  status_change: {
    icon: 'check-square',
    label: 'Status change',
    ring: 'bg-surface-2 text-default border-subtle',
  },
  task: {
    icon: 'check',
    label: 'Task',
    ring: 'bg-fuchsia-100 text-fuchsia-700 ring-fuchsia-200',
  },
};

const FALLBACK_META: TypeMeta = {
  icon: 'sticky-note',
  label: 'Activity',
  ring: 'bg-surface-2 text-default border-subtle',
};

interface DayGroup {
  dayKey: string;
  dayLabel: string;
  items: StaffActivity[];
}

/**
 * Activity Log tab — per-staff stream pulled from
 * `/api/v1/staff/{user_id}/activity`. Items group by local calendar
 * day, newest first; "Today" / "Yesterday" relabel matches the
 * timeline in Step 2.6 so admins read the same shape across views.
 */
@Component({
  selector: 'app-staff-activity-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RelativeTimePipe, MobileSelectComponent],
  templateUrl: './activity.component.html',
})
export class StaffActivityTabComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly rows = input.required<StaffWithPerformance[]>();

  protected readonly selectedUserId = signal<string | null>(null);
  protected readonly activities = signal<StaffActivity[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly staffOptions = computed<MobileSelectOption[]>(() =>
    this.rows().map((r) => ({ value: r.staff.id, label: r.staff.full_name })),
  );

  protected readonly groups = computed<DayGroup[]>(() => {
    const byKey = new Map<string, DayGroup>();
    for (const item of this.activities()) {
      const d = new Date(item.created_at);
      const key = d.toISOString().slice(0, 10);
      let g = byKey.get(key);
      if (!g) {
        g = { dayKey: key, dayLabel: this.dayLabel(d), items: [] };
        byKey.set(key, g);
      }
      g.items.push(item);
    }
    return [...byKey.values()].sort((a, b) => b.dayKey.localeCompare(a.dayKey));
  });

  constructor() {
    effect(() => {
      const list = this.rows();
      if (list.length > 0 && this.selectedUserId() === null) {
        this.selectedUserId.set(list[0].staff.id);
      }
    });
    effect(() => {
      const id = this.selectedUserId();
      if (id) this.fetch(id);
    });
  }

  protected pickStaff(value: string): void {
    this.selectedUserId.set(value || null);
  }

  protected metaFor(type: string): TypeMeta {
    return TYPE_META[type] ?? FALLBACK_META;
  }

  protected snippet(a: StaffActivity): string {
    const text = (a.payload as { text?: unknown })?.text;
    if (typeof text === 'string' && text.length > 0) return text;
    return this.metaFor(a.type).label;
  }

  protected entityLabel(a: StaffActivity): string {
    return `${a.entity_type} · ${a.entity_id.slice(0, 8)}`;
  }

  private dayLabel(d: Date): string {
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

  private fetch(userId: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .activity(userId, 100)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.activities.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.activities.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load activity.');
        },
      });
  }
}
