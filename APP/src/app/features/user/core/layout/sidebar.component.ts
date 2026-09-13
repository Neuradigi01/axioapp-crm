import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { UpperCasePipe } from '@angular/common';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { BrandService } from '@core/services/brand.service';

import { FurnitureAuthService } from '../auth/auth.service';
import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';
import { NotificationsApiService } from '../notifications/notifications-api.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, LucideAngularModule, UpperCasePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.component.html',
})
export class SidebarComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly router = inject(Router);
  /** Shown when an org has no name yet — must read as the product, not a constant. */
  protected readonly brand = inject(BrandService).brand;

  /** Desktop expand/collapse state. */
  readonly expanded = input.required<boolean>();
  /** Desktop collapse/expand toggle (chevron button). */
  readonly toggle = output<void>();

  /** Current tenant — drives the workspace-switcher card at the top of
   * the rail. `null` until the first `/me` response lands. */
  protected readonly org = this.auth.currentOrg;

  /** Signed-in user's role — shown in the bottom profile card. */
  protected readonly roleName = this.auth.currentRoleName;

  /** Registry-driven module list (unchanged from Step 2.5 wiring). */
  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly error = signal<string | null>(null);

  /** Modules grouped into consecutive same-section RUNS (AIXO layout).
   *
   * AIXO deliberately alternates section headers by usage flow, so
   * `My Work` and `Engage` legitimately appear twice each. We must NOT
   * dedupe on section string — instead walk modules in `menu_position`
   * order and open a new group every time `section` changes. Modules
   * with `section=null` are excluded here and rendered in the pinned
   * footer group at the bottom of the rail.
   */
  protected readonly groupedModules = computed<
    Array<{ section: string; items: ModuleDescriptorOut[] }>
  >(() => {
    const groups: Array<{ section: string; items: ModuleDescriptorOut[] }> = [];
    let current: { section: string; items: ModuleDescriptorOut[] } | null = null;
    for (const mod of this.modules()) {
      if (!mod.section) continue;
      if (!current || current.section !== mod.section) {
        current = { section: mod.section, items: [] };
        groups.push(current);
      }
      current.items.push(mod);
    }
    return groups;
  });

  /** Modules with no `section` — render at the bottom of the rail
   * (Integrations, Subscription, Settings, pack billing). No header. */
  protected readonly footerModules = computed<ModuleDescriptorOut[]>(() =>
    this.modules().filter((m) => !m.section),
  );

  /** Workspace-switcher popover open state. */
  protected readonly wsMenuOpen = signal(false);

  /** First letter of the workspace name — accent-tinted square avatar. */
  protected readonly wsInitial = computed(() => {
    const name = this.org()?.name ?? 'C';
    return name.charAt(0).toUpperCase();
  });

  /** Friendly pack/template display name shown under the org name in
   *  the workspace card ("Real Estate" instead of "real_estate"). Falls
   *  back to a title-cased slug so a new pack still renders sensibly. */
  private readonly TEMPLATE_LABELS: Record<string, string> = {
    base: 'CRM',
    real_estate: 'Real Estate',
    furniture: 'Furniture',
    clinic: 'Clinic',
    salon: 'Salon',
    services: 'Services',
  };

  protected readonly workspaceLabel = computed<string>(() => {
    const tid = this.org()?.template_id;
    if (!tid) return 'CRM';
    if (tid in this.TEMPLATE_LABELS) return this.TEMPLATE_LABELS[tid];
    return tid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  });

  /** Signed-in user's initial — bottom profile avatar. */
  protected readonly userInitial = computed(() => {
    const name = this.auth.currentRoleName();
    return name ? name.charAt(0).toUpperCase() : 'U';
  });

  toggleWsMenu(): void {
    this.wsMenuOpen.update((v) => !v);
  }

  closeWsMenu(): void {
    this.wsMenuOpen.set(false);
  }

  logout(): void {
    this.closeWsMenu();
    this.auth.logout().subscribe({
      next: () => this.afterLogout(),
      error: () => this.afterLogout(),
    });
  }

  private afterLogout(): void {
    this.notifications.stop();
    this.auth.clearSession();
    this.router.navigate(['/accounts/login']);
  }

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.error.set('Could not load modules.'),
    });
  }
}
