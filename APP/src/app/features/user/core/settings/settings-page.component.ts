import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { CustomFieldsPageComponent } from '../custom-fields/custom-fields.page';
import { AiSettingsTabComponent } from './tabs/ai-settings-tab.component';
import { IntegrationsTabComponent } from './tabs/integrations-tab.component';
import { NotificationsTabComponent } from './tabs/notifications-tab.component';
import { RolesTabComponent } from './tabs/roles-tab.component';
import { StoreProfileTabComponent } from './tabs/store-profile-tab.component';
import { TeamTabComponent } from './tabs/team-tab.component';

type SettingsTab =
  | 'store'
  | 'team'
  | 'roles'
  | 'integrations'
  | 'notifications'
  | 'ai'
  | 'custom-fields';

const TABS: ReadonlyArray<{ id: SettingsTab; label: string }> = [
  { id: 'store', label: 'Store Profile' },
  { id: 'team', label: 'Team' },
  { id: 'roles', label: 'Roles' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'ai', label: 'AI Settings' },
  { id: 'custom-fields', label: 'Custom Fields' },
];

@Component({
  selector: 'app-settings-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    StoreProfileTabComponent,
    TeamTabComponent,
    RolesTabComponent,
    IntegrationsTabComponent,
    NotificationsTabComponent,
    AiSettingsTabComponent,
    CustomFieldsPageComponent,
  ],
  templateUrl: './settings-page.component.html',
})
export class SettingsPageComponent {
  readonly tabs = TABS;
  readonly active = signal<SettingsTab>(TABS[0].id);
}
