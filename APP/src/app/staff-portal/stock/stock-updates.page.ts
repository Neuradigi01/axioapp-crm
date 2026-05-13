import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-stock-updates-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 bg-white p-8 text-center">
      <h2 class="text-lg font-semibold text-zinc-900">Stock Updates</h2>
      <p class="max-w-md text-sm text-zinc-500">
        Reporting stock in/out from the shop floor lands in Phase 4.4 with the
        multi-location inventory module.
      </p>
    </div>
  `,
})
export class StockUpdatesPageComponent {}
