import { ChangeDetectionStrategy, Component } from '@angular/core';

import {
  dashboardRange,
  setDashboardRange,
  type DashboardRange,
} from './dashboard-range.signal';

/**
 * Segmented [7D | 30D | 90D | 365D] control that drives every dashboard
 * widget through the shared `dashboardRange` signal.
 *
 * Fully self-contained — no inputs, no outputs. The signal is the
 * integration point: widgets subscribe to `dashboardRange()` and
 * re-fetch whenever it changes.
 */
@Component({
  selector: 'app-dashboard-date-range',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard-date-range.component.html',
})
export class DashboardDateRangeComponent {
  protected readonly options: ReadonlyArray<{ value: DashboardRange; label: string }> = [
    { value: '7d', label: '7D' },
    { value: '30d', label: '30D' },
    { value: '90d', label: '90D' },
    { value: '365d', label: '365D' },
  ];

  protected readonly active = dashboardRange;

  protected select(next: DashboardRange): void {
    setDashboardRange(next);
  }
}
