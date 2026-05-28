import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { StaffApiService, WorkloadUser } from './staff-api.service';

type SortKey =
  | 'name'
  | 'contacts'
  | 'leads'
  | 'walk_ins'
  | 'appointments'
  | 'tasks'
  | 'total';
type SortDir = 'asc' | 'desc';

/**
 * Workload sub-tab — per-user open-record counts across the org.
 *
 * Same predicates as the deactivation modal's counts endpoint
 * (compute_workload re-uses compute_open_records_counts on the
 * backend) so the two surfaces never disagree.
 *
 * Sortable by any column; the user with the largest `total` is
 * highlighted with a light zinc bg as the visual cue (heaviest load).
 */
@Component({
  selector: 'app-staff-workload',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, LucideAngularModule],
  templateUrl: './staff-workload.component.html',
})
export class StaffWorkloadComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<WorkloadUser[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly asOf = signal<string | null>(null);

  protected readonly sortKey = signal<SortKey>('total');
  protected readonly sortDir = signal<SortDir>('desc');

  protected readonly sorted = computed(() => {
    const list = [...this.rows()];
    const key = this.sortKey();
    const dir = this.sortDir();
    const cmp = (a: WorkloadUser, b: WorkloadUser) => {
      if (key === 'name') {
        const an = `${a.first_name} ${a.last_name}`.trim().toLowerCase();
        const bn = `${b.first_name} ${b.last_name}`.trim().toLowerCase();
        return an < bn ? -1 : an > bn ? 1 : 0;
      }
      const av = a.counts[key];
      const bv = b.counts[key];
      return av - bv;
    };
    list.sort((a, b) => (dir === 'asc' ? cmp(a, b) : -cmp(a, b)));
    return list;
  });

  /** Id of the user with the largest workload — visual highlight. */
  protected readonly heaviestId = computed(() => {
    let max = -1;
    let id: string | null = null;
    for (const u of this.rows()) {
      if (u.counts.total > max) {
        max = u.counts.total;
        id = u.user_id;
      }
    }
    return max > 0 ? id : null;
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getWorkload(true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (report) => {
          this.rows.set(report.users);
          this.asOf.set(report.as_of);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.rows.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load workload report.',
          );
        },
      });
  }

  protected setSort(key: SortKey): void {
    if (this.sortKey() === key) {
      this.sortDir.set(this.sortDir() === 'asc' ? 'desc' : 'asc');
    } else {
      this.sortKey.set(key);
      // Numeric columns default to desc (biggest first); name defaults to asc.
      this.sortDir.set(key === 'name' ? 'asc' : 'desc');
    }
  }

  protected fullName(u: WorkloadUser): string {
    const name = `${u.first_name} ${u.last_name}`.trim();
    return name || '—';
  }
}
