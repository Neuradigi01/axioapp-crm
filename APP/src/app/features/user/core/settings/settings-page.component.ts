import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';

import { CustomFieldsPageComponent } from '../custom-fields/custom-fields.page';
import { FurnitureAuthService } from '../auth/auth.service';
import { AiSettingsTabComponent } from './tabs/ai-settings-tab.component';
import { EmbedIntegrationsTabComponent } from './tabs/embed-integrations-tab.component';
import { IntegrationsTabComponent } from './tabs/integrations-tab.component';
import { NotificationsTabComponent } from './tabs/notifications-tab.component';
import { RolesTabComponent } from './tabs/roles-tab.component';
import { StandardFieldsTabComponent } from './tabs/standard-fields-tab.component';
import { StoreProfileTabComponent } from './tabs/store-profile-tab.component';
import { TeamTabComponent } from './tabs/team-tab.component';

type SettingsTab =
  | 'store'
  | 'team'
  | 'roles'
  | 'integrations'
  | 'notifications'
  | 'ai'
  | 'custom-fields'
  | 'standard-fields'
  | 'embed';

interface TabDef {
  id: SettingsTab;
  label: string;
  /** If set, the tab is hidden unless the current user holds this permission. */
  permission?: string;
}

const TABS: ReadonlyArray<TabDef> = [
  { id: 'store', label: 'Store Profile' },
  { id: 'team', label: 'Team' },
  { id: 'roles', label: 'Roles' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'ai', label: 'AI Settings' },
  { id: 'custom-fields', label: 'Custom Fields' },
  {
    id: 'standard-fields',
    label: 'Standard Fields',
    permission: 'settings.standard_fields.manage',
  },
  {
    id: 'embed',
    label: 'Embed Widget',
    permission: 'settings.integrations.embed.manage',
  },
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
    StandardFieldsTabComponent,
    EmbedIntegrationsTabComponent,
  ],
  templateUrl: './settings-page.component.html',
})
export class SettingsPageComponent {
  private readonly auth = inject(FurnitureAuthService);

  readonly tabs = computed(() =>
    TABS.filter((t) => !t.permission || this.auth.hasPermission(t.permission)),
  );
  readonly active = signal<SettingsTab>(TABS[0].id);
}
