import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { InrPipe } from '../../shared/pipes/inr.pipe';
import { StaffWithPerformance } from '../staff-api.service';
import { progressTone, progressWidth } from '../staff-display.util';

/**
 * Leaderboard tab — staff ranked by `performance.target_progress_pct`
 * descending. Rows with no profile (null target_progress) fall to the
 * bottom rather than crashing the sort.
 */
@Component({
  selector: 'app-staff-leaderboard-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe],
  templateUrl: './leaderboard.component.html',
})
export class StaffLeaderboardTabComponent {
  readonly rows = input.required<StaffWithPerformance[]>();
  protected readonly progressTone = progressTone;
  protected readonly progressWidth = progressWidth;

  protected readonly ranked = computed(() =>
    [...this.rows()].sort((a, b) => {
      const ap = a.performance.target_progress_pct ?? -1;
      const bp = b.performance.target_progress_pct ?? -1;
      return bp - ap;
    }),
  );

  protected rankBadge(idx: number): string {
    if (idx === 0) return 'bg-amber-100 text-amber-700 ring-amber-200';
    if (idx === 1) return 'bg-slate-400/20 text-slate-500 ring-slate-400/40';
    if (idx === 2) return 'bg-orange-100 text-orange-700 ring-orange-200';
    return 'bg-surface-2 text-muted ring-subtle';
  }
}
