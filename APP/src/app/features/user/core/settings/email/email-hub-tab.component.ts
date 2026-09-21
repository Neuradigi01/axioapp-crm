/**
 * Email settings hub — one Settings tab, six sub-tabs.
 *
 * Consolidates the shipped ``Sending Domains``, ``Inbound Addresses``,
 * and ``Reputation`` sidebar entries with the Track 5 / 6 additions
 * (``Held Mail`` = quarantine, ``Blocked Senders`` = filter rules,
 * ``Audit Log`` = platform-staff mailgun webhook receipts) into one
 * Prativani-style tabbed page.
 *
 * **Zero changes to the underlying tab components.** This shell only
 * imports them and displays one at a time based on the sub-tab
 * selector. Persistence: query param ``?email_tab=...`` so a URL
 * copy-paste or a browser refresh lands on the same tab. Permission
 * gating: each sub-tab checks its shipped permission key; tabs the
 * user can't access are hidden entirely.
 */
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { FurnitureAuthService } from '../../auth/auth.service';
import { AuditLogTabComponent } from './audit-log-tab.component';
import { BlocklistTabComponent } from './blocklist-tab.component';
import { InboundAddressesTabComponent } from './inbound-addresses-tab.component';
import { QuarantineTabComponent } from './quarantine-tab.component';
import { ReputationDashboardTabComponent } from './reputation-dashboard-tab.component';
import { SendingDomainsTabComponent } from './sending-domains-tab.component';

type EmailSubTab = 'addresses' | 'domains' | 'reputation' | 'held' | 'blocked' | 'audit';

interface SubTabDef {
  id: EmailSubTab;
  label: string;
  /** Optional permission gate; missing = visible to any user who can
   * reach the parent Settings → Email tab. */
  permission?: string;
}

const SUB_TABS: ReadonlyArray<SubTabDef> = [
  { id: 'addresses', label: 'Addresses', permission: 'email.accounts.manage' },
  {
    id: 'domains',
    label: 'Sending domains',
    permission: 'email.sending_domains.manage',
  },
  {
    id: 'reputation',
    label: 'Reputation',
    permission: 'email.sending_domains.manage',
  },
  { id: 'held', label: 'Held mail', permission: 'email.accounts.manage' },
  {
    id: 'blocked',
    label: 'Blocked senders',
    permission: 'email.accounts.manage',
  },
  {
    id: 'audit',
    label: 'Audit log',
    permission: 'mailgun.inbound.dlq.manage',
  },
];

@Component({
  selector: 'app-email-hub-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    SendingDomainsTabComponent,
    InboundAddressesTabComponent,
    ReputationDashboardTabComponent,
    QuarantineTabComponent,
    BlocklistTabComponent,
    AuditLogTabComponent,
  ],
  templateUrl: './email-hub-tab.component.html',
})
export class EmailHubTabComponent {
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly visibleSubTabs = computed(() =>
    SUB_TABS.filter((t) => !t.permission || this.auth.hasPermission(t.permission)),
  );

  readonly active = signal<EmailSubTab>(this._resolveInitial());

  select(id: EmailSubTab): void {
    if (this.active() === id) return;
    this.active.set(id);
    // Preserve tab on refresh / URL share. Merge to avoid clobbering
    // the parent settings-page's ``tab=email`` query param.
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { email_tab: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  private _resolveInitial(): EmailSubTab {
    const qp = this.route.snapshot.queryParamMap.get('email_tab') as EmailSubTab | null;
    if (qp && this._isVisible(qp)) return qp;
    const visible = this.visibleSubTabs();
    return visible[0]?.id ?? 'addresses';
  }

  private _isVisible(id: EmailSubTab): boolean {
    const def = SUB_TABS.find((t) => t.id === id);
    if (!def) return false;
    return !def.permission || this.auth.hasPermission(def.permission);
  }
}
