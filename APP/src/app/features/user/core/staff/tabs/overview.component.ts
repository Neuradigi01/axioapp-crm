import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { InrPipe } from '../../shared/pipes/inr.pipe';
import { StaffWithPerformance } from '../staff-api.service';
import {
  conversionPct,
  employmentStatusBadge,
  progressTone,
  progressWidth,
} from '../staff-display.util';
import { initials } from '@core/services/text.util';

/**
 * Overview tab — grid of staff "summary cards". One card per user
 * showing the joined profile + performance numbers we have today.
 * Avatar background is a deterministic hash on user.id so the same
 * person keeps the same colour across reloads.
 */
@Component({
  selector: 'app-staff-overview-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, InrPipe],
  templateUrl: './overview.component.html',
})
export class StaffOverviewTabComponent {
  protected readonly initials = initials;
  protected readonly statusBadge = employmentStatusBadge;
  protected readonly progressTone = progressTone;
  protected readonly progressWidth = progressWidth;
  protected readonly conversionPct = conversionPct;
  readonly rows = input.required<StaffWithPerformance[]>();

  /** Client-side name / email filter — the roster is already loaded. */
  protected readonly query = signal('');

  protected readonly sortedRows = computed(() =>
    [...this.rows()].sort((a, b) => a.staff.full_name.localeCompare(b.staff.full_name)),
  );

  protected readonly visibleRows = computed(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return this.sortedRows();
    return this.sortedRows().filter(
      (r) =>
        r.staff.full_name.toLowerCase().includes(q) ||
        (r.staff.email ?? '').toLowerCase().includes(q),
    );
  });

  protected avatarBg(id: string): string {
    const palette = [
      'bg-red-500/10 text-red-400',
      'bg-amber-100 text-amber-700',
      'bg-emerald-100 text-emerald-700',
      'bg-sky-100 text-sky-700',
      'bg-violet-100 text-violet-700',
      'bg-fuchsia-100 text-fuchsia-700',
    ];
    let h = 0;
    for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  }
}
