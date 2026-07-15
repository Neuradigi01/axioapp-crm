import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { ThemeChoice, ThemeService } from '@core/services/theme.service';

interface ThemeOption {
  id: ThemeChoice;
  label: string;
  hint: string;
}

/**
 * Settings → Appearance tab. Three-card picker for the user's theme
 * preference (Light / Dark / System). Backed by `ThemeService` —
 * persists via `localStorage` and applies instantly. `'system'` keeps
 * tracking the OS preference live via `matchMedia` change events.
 */
@Component({
  selector: 'app-settings-appearance-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './appearance-tab.component.html',
})
export class AppearanceTabComponent {
  private readonly theme = inject(ThemeService);

  protected readonly choice = this.theme.choice;

  protected readonly options: readonly ThemeOption[] = [
    { id: 'light', label: 'Light', hint: 'Always bright' },
    { id: 'dark', label: 'Dark', hint: 'Always dim' },
    { id: 'system', label: 'System', hint: 'Match your OS' },
  ];

  protected pick(c: ThemeChoice): void {
    this.theme.set(c);
  }
}
