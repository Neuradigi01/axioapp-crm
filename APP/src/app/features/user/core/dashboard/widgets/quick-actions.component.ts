import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../../auth/auth.service';

interface QuickAction {
  key: 'new_lead' | 'log_call' | 'schedule_meeting' | 'add_contact';
  label: string;
  icon: string;
  permission: string;
  routerLink: string;
  queryParams: Record<string, string>;
}

/**
 * Dashboard quick-actions toolbar: 4 routerLink buttons that drop the
 * user into the create-modal of the relevant page. Each button is
 * gated by the matching `*.write` permission, so a Junior Sales Exec
 * without `appointments.write` simply doesn't see the "Schedule
 * meeting" button. If none of the four are visible the whole section
 * collapses — no empty toolbar.
 *
 * The destination pages each read `?new=1` on init and open their
 * existing create modal (existing convention used by the quick-add FAB).
 */
@Component({
  selector: 'app-dashboard-quick-actions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './quick-actions.component.html',
})
export class QuickActionsComponent {
  private readonly auth = inject(FurnitureAuthService);

  private readonly ACTIONS: ReadonlyArray<QuickAction> = [
    {
      key: 'new_lead',
      label: 'New lead',
      icon: 'plus',
      permission: 'leads.write',
      routerLink: '/user/leads',
      queryParams: { new: '1' },
    },
    {
      key: 'log_call',
      label: 'Log call',
      icon: 'phone',
      permission: 'calls.write',
      routerLink: '/user/calls',
      queryParams: { new: '1' },
    },
    {
      key: 'schedule_meeting',
      label: 'Schedule meeting',
      icon: 'calendar',
      permission: 'appointments.write',
      routerLink: '/user/appointments',
      queryParams: { new: '1' },
    },
    {
      key: 'add_contact',
      label: 'Add contact',
      icon: 'user-plus',
      permission: 'contacts.write',
      routerLink: '/user/contacts',
      queryParams: { new: '1' },
    },
  ];

  protected readonly visible = computed<QuickAction[]>(() => {
    const granted = new Set(this.auth.currentPermissions());
    return this.ACTIONS.filter((a) => granted.has(a.permission));
  });
}
