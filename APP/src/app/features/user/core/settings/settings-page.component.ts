import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { CustomFieldsPageComponent } from '../custom-fields/custom-fields.page';
import { FurnitureAuthService } from '../auth/auth.service';
import { EmailAccountsTabComponent } from './email-accounts/email-accounts-tab.component';
import { EmailSequencesListComponent } from './email-sequences/sequence-list.component';
import { AiSettingsTabComponent } from './tabs/ai-settings-tab.component';
import { AppearanceTabComponent } from './tabs/appearance-tab.component';
import { AutomationSettingsTabComponent } from './tabs/automation-settings-tab.component';
import { EmbedIntegrationsTabComponent } from './tabs/embed-integrations-tab.component';
import { LoginHistoryTabComponent } from './tabs/login-history-tab.component';
import { NotificationsTabComponent } from './tabs/notifications-tab.component';
import { ProfileTabComponent } from './tabs/profile-tab.component';
import { RolesTabComponent } from './tabs/roles-tab.component';
import { StandardFieldsTabComponent } from './tabs/standard-fields-tab.component';
import { StoreProfileTabComponent } from './tabs/store-profile-tab.component';
import { TeamTabComponent } from './tabs/team-tab.component';
import { TwoFactorTabComponent } from './tabs/two-factor-tab.component';

type SettingsTab =
  | 'profile'
  | 'appearance'
  | 'two-factor'
  | 'login-history'
  | 'store'
  | 'team'
  | 'roles'
  | 'email-accounts'
  | 'email-sequences'
  | 'notifications'
  | 'ai'
  | 'send-rules'
  | 'custom-fields'
  | 'standard-fields'
  | 'embed';

interface TabDef {
  id: SettingsTab;
  label: string;
  /** If set, the tab is hidden unless the current user holds this permission. */
  permission?: string;
}

/**
 * Tabs that mutate org-wide state are gated by an explicit permission
 * key. `Notifications` is a personal preference (per-user email opt-in
 * etc.) so it stays open to every authenticated user — Employees land
 * straight on it when they open `/user/settings`.
 */
const TABS: ReadonlyArray<TabDef> = [
  { id: 'profile', label: 'Profile' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'two-factor', label: 'Two-factor' },
  { id: 'login-history', label: 'Login history' },
  { id: 'store', label: 'Store Profile', permission: 'settings.write' },
  { id: 'team', label: 'Team', permission: 'users.read' },
  { id: 'roles', label: 'Roles', permission: 'roles.read' },
  {
    // App-updates Email Step 9 — per-user mailbox management. Every
    // role with `email.accounts.manage` (Owner/Admin/Employee/
    // SalesManager/SupportAgent per Step 1's role-template grants)
    // sees this tab; the backend list endpoint returns own-only for
    // reps and all-org for Owner/Admin holding `email.accounts.admin`.
    id: 'email-accounts',
    label: 'Email Accounts',
    permission: 'email.accounts.manage',
  },
  {
    // tasks/template-library Step 10 — the standalone Email Templates
    // tab moved into the central `/user/templates` library. The
    // sequence-builder still uses email templates via the central
    // API; the tab itself is gone.
    // App-updates Email Step 11a — sequence library. Visible to
    // anyone with `email.read`; Create / Edit / Delete affordances
    // gate on `email.sequences.manage` inside the list component.
    id: 'email-sequences',
    label: 'Email Sequences',
    permission: 'email.read',
  },
  { id: 'ai', label: 'AI Settings', permission: 'settings.write' },
  {
    // tasks/automation-engine Step 13 — quiet hours, frequency cap,
    // DPDP marketing-consent note. Owner / Admin only via
    // `settings.write`.
    id: 'send-rules',
    label: 'Send Rules',
    permission: 'settings.write',
  },
  {
    id: 'custom-fields',
    label: 'Custom Fields',
    permission: 'custom_fields.write',
  },
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
    ProfileTabComponent,
    AppearanceTabComponent,
    TwoFactorTabComponent,
    LoginHistoryTabComponent,
    StoreProfileTabComponent,
    TeamTabComponent,
    RolesTabComponent,
    NotificationsTabComponent,
    AiSettingsTabComponent,
    AutomationSettingsTabComponent,
    CustomFieldsPageComponent,
    StandardFieldsTabComponent,
    EmbedIntegrationsTabComponent,
    EmailAccountsTabComponent,
    EmailSequencesListComponent,
  ],
  templateUrl: './settings-page.component.html',
})
export class SettingsPageComponent {
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);

  readonly tabs = computed(() =>
    TABS.filter((t) => !t.permission || this.auth.hasPermission(t.permission)),
  );

  // Initial tab resolution priority (Step 7):
  //   1. route.data.tab (set by /user/settings/integrations alias)
  //   2. query param `tab=...` (lets OAuth callback bounce land us
  //      on the integrations tab via `?tab=integrations&status=…`)
  //   3. first tab the user has permission for (falls back to store)
  readonly active = signal<SettingsTab>(this._resolveInitialTab());

  private _resolveInitialTab(): SettingsTab {
    const routeData = this.route.snapshot.data['tab'] as
      | SettingsTab
      | undefined;
    if (routeData && this._isVisible(routeData)) return routeData;
    const qp = this.route.snapshot.queryParamMap.get('tab') as
      | SettingsTab
      | null;
    if (qp && this._isVisible(qp)) return qp;
    const visible = TABS.filter(
      (t) => !t.permission || this.auth.hasPermission(t.permission),
    );
    return (visible[0]?.id ?? TABS[0].id) as SettingsTab;
  }

  private _isVisible(id: SettingsTab): boolean {
    const def = TABS.find((t) => t.id === id);
    if (!def) return false;
    return !def.permission || this.auth.hasPermission(def.permission);
  }
}
