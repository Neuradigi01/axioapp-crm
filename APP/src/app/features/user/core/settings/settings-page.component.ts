import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { CustomFieldsPageComponent } from '../custom-fields/custom-fields.page';
import { FurnitureAuthService } from '../auth/auth.service';
import { CustomEventsPageComponent } from './custom-events/custom-events.page';
import { EmailHubTabComponent } from './email/email-hub-tab.component';
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
  | 'notifications'
  | 'email'
  | 'send-rules'
  | 'custom-events'
  | 'custom-fields'
  | 'standard-fields'
  | 'embed';

type SettingsGroup = 'account' | 'workspace' | 'automation' | 'data';

interface TabDef {
  id: SettingsTab;
  label: string;
  group: SettingsGroup;
  /** If set, the tab is hidden unless the current user holds this permission. */
  permission?: string;
}

interface GroupedTabs {
  id: SettingsGroup;
  label: string;
  tabs: ReadonlyArray<TabDef>;
}

const GROUP_LABELS: Record<SettingsGroup, string> = {
  account: 'Account',
  workspace: 'Workspace',
  automation: 'Automation',
  data: 'Data & Fields',
};

const GROUP_ORDER: ReadonlyArray<SettingsGroup> = ['account', 'workspace', 'automation', 'data'];

/**
 * Tabs that mutate org-wide state are gated by an explicit permission
 * key. `Notifications` is a personal preference (per-user email opt-in
 * etc.) so it stays open to every authenticated user — Employees land
 * straight on it when they open `/user/settings`.
 */
const TABS: ReadonlyArray<TabDef> = [
  { id: 'profile', label: 'Profile', group: 'account' },
  { id: 'appearance', label: 'Appearance', group: 'account' },
  { id: 'notifications', label: 'Notifications', group: 'account' },
  { id: 'two-factor', label: 'Two-factor', group: 'account' },
  { id: 'login-history', label: 'Login history', group: 'account' },
  { id: 'store', label: 'Store Profile', group: 'workspace', permission: 'settings.write' },
  { id: 'team', label: 'Team', group: 'workspace', permission: 'users.read' },
  { id: 'roles', label: 'Roles', group: 'workspace', permission: 'roles.read' },
  {
    // Consolidated email settings hub — Prativani-style. One sidebar
    // entry that hosts Addresses / Sending domains / Reputation / Held
    // mail (quarantine) / Blocked senders (filter rules) / Audit log as
    // sub-tabs. Replaces the previously-shipped three separate entries
    // for Sending Domains, Inbound Addresses, and Reputation. Gated by
    // ``email.accounts.manage`` — the loosest of the sub-tab permissions,
    // so any user who can reach ANY sub-tab can reach the hub; the hub
    // itself hides sub-tabs the user lacks permission for.
    id: 'email',
    label: 'Email',
    group: 'workspace',
    permission: 'email.accounts.manage',
  },
  // Email Accounts + Sender Setup tabs were consolidated into the
  // per-org Email Sender card on Settings → Integrations.
  // tasks/workflows Step 20 — the Email Sequences tab was absorbed
  // into Workflows. The standalone tab + builder routes redirect to
  // /user/workflows?category=Marketing (see user.routes.ts).
  {
    // tasks/automation-engine Step 13 — quiet hours, frequency cap,
    // DPDP marketing-consent note. Owner / Admin only via
    // `settings.write`.
    id: 'send-rules',
    label: 'Send Rules',
    group: 'automation',
    permission: 'settings.write',
  },
  {
    // tasks/custom-events — org-defined named triggers. Everyone with
    // a login sees the tab so they can also fire events from the
    // contact page's dropdown; create / edit / delete is Owner+Admin
    // by permission on the CRUD endpoints (custom_events.manage).
    id: 'custom-events',
    label: 'Custom Events',
    group: 'automation',
    permission: 'custom_events.read',
  },
  {
    id: 'custom-fields',
    label: 'Custom Fields',
    group: 'data',
    permission: 'custom_fields.write',
  },
  {
    id: 'standard-fields',
    label: 'Standard Fields',
    group: 'data',
    permission: 'settings.standard_fields.manage',
  },
  {
    // Multi-form track: the settings tab is now "Forms" and lists
    // every widget form the org owns (Contact Us, Newsletter, etc.).
    // Tab id stays `embed` so bookmarks + URL query params keep working.
    id: 'embed',
    label: 'Forms',
    group: 'data',
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
    EmailHubTabComponent,
    AutomationSettingsTabComponent,
    CustomEventsPageComponent,
    CustomFieldsPageComponent,
    StandardFieldsTabComponent,
    EmbedIntegrationsTabComponent,
    LucideAngularModule,
  ],
  templateUrl: './settings-page.component.html',
})
export class SettingsPageComponent {
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);

  readonly tabs = computed(() =>
    TABS.filter((t) => !t.permission || this.auth.hasPermission(t.permission)),
  );

  readonly groupedTabs = computed<ReadonlyArray<GroupedTabs>>(() => {
    const visible = this.tabs();
    return GROUP_ORDER.map((g) => ({
      id: g,
      label: GROUP_LABELS[g],
      tabs: visible.filter((t) => t.group === g),
    })).filter((g) => g.tabs.length > 0);
  });

  /** Label of the currently-active tab — shown in the mobile picker
   *  button so the user always sees which section they're on. */
  readonly activeLabel = computed(() => {
    const id = this.active();
    return this.tabs().find((t) => t.id === id)?.label ?? '';
  });

  /** Mobile picker open/closed state. */
  readonly mobilePickerOpen = signal(false);

  toggleMobilePicker(): void {
    this.mobilePickerOpen.update((v) => !v);
  }

  pickMobile(id: SettingsTab): void {
    this.active.set(id);
    this.mobilePickerOpen.set(false);
  }

  // Initial tab resolution priority (Step 7):
  //   1. route.data.tab (set by /user/settings/integrations alias)
  //   2. query param `tab=...` (lets OAuth callback bounce land us
  //      on the integrations tab via `?tab=integrations&status=…`)
  //   3. first tab the user has permission for (falls back to store)
  readonly active = signal<SettingsTab>(this._resolveInitialTab());

  private _resolveInitialTab(): SettingsTab {
    const routeData = this.route.snapshot.data['tab'] as SettingsTab | undefined;
    if (routeData && this._isVisible(routeData)) return routeData;
    const qp = this.route.snapshot.queryParamMap.get('tab') as SettingsTab | null;
    if (qp && this._isVisible(qp)) return qp;
    const visible = TABS.filter((t) => !t.permission || this.auth.hasPermission(t.permission));
    return (visible[0]?.id ?? TABS[0].id) as SettingsTab;
  }

  private _isVisible(id: SettingsTab): boolean {
    const def = TABS.find((t) => t.id === id);
    if (!def) return false;
    return !def.permission || this.auth.hasPermission(def.permission);
  }
}
