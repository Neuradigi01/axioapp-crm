import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-settings-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="p-8">
      <h1 class="text-2xl font-semibold text-zinc-900">Settings</h1>
      <p class="mt-2 text-sm text-zinc-500">Settings (coming soon)</p>
    </div>
  `,
})
export class SettingsPageComponent {}
