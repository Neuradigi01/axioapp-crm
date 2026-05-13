import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-field-visits-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 bg-white p-8 text-center">
      <h2 class="text-lg font-semibold text-zinc-900">Field Visits</h2>
      <p class="max-w-md text-sm text-zinc-500">
        Site visits, deliveries and route assignments arrive in Phase 4.10 with the
        furniture pack's field-ops module.
      </p>
    </div>
  `,
})
export class FieldVisitsPageComponent {}
