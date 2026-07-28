import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { InrPipe } from '../../shared/pipes/inr.pipe';
import { StaffWithPerformance } from '../staff-api.service';
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
  readonly rows = input.required<StaffWithPerformance[]>();

  protected readonly sortedRows = computed(() =>
    [...this.rows()].sort((a, b) => a.staff.full_name.localeCompare(b.staff.full_name)),
  );

  protected avatarBg(id: string): string {
    const palette = [
      'bg-rose-100 text-rose-700',
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

  protected statusBadge(status: string | null): {
    label: string;
    cls: string;
  } {
    switch (status) {
      case 'active':
        return {
          label: 'Active',
          cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        };
      case 'leave':
        return {
          label: 'On Leave',
          cls: 'bg-amber-50 text-amber-700 ring-amber-200',
        };
      case 'terminated':
        return {
          label: 'Off-boarded',
          cls: 'bg-rose-50 text-rose-700 ring-rose-200',
        };
      default:
        return {
          label: 'No profile',
          cls: 'bg-surface-2 text-muted border-subtle',
        };
    }
  }
}
