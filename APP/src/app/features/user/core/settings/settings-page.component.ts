import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { CustomFieldsPageComponent } from '../custom-fields/custom-fields.page';

type SettingsTab = 'custom-fields';

const TABS: ReadonlyArray<{ id: SettingsTab; label: string }> = [
  { id: 'custom-fields', label: 'Custom Fields' },
];

@Component({
  selector: 'app-settings-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CustomFieldsPageComponent],
  templateUrl: './settings-page.component.html',
})
export class SettingsPageComponent {
  readonly tabs = TABS;
  readonly active = signal<SettingsTab>(TABS[0].id);
}
