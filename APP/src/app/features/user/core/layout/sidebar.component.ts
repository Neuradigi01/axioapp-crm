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
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';
import { NotificationsApiService } from '../notifications/notifications-api.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.component.html',
})
export class SidebarComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly router = inject(Router);

  /** Desktop expand/collapse state. */
  readonly expanded = input.required<boolean>();
  /** Mobile off-canvas drawer open state. */
  readonly mobileOpen = input.required<boolean>();
  /** Desktop collapse/expand toggle (chevron button). */
  readonly toggle = output<void>();
  /** Mobile drawer close (X button or nav-link tap). */
  readonly close = output<void>();

  /** Current tenant — drives the workspace-switcher card at the top of
   * the rail. `null` until the first `/me` response lands. */
  protected readonly org = this.auth.currentOrg;

  /** Signed-in user's role — shown in the bottom profile card. */
  protected readonly roleName = this.auth.currentRoleName;

  /** Registry-driven module list (unchanged from Step 2.5 wiring). */
  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly error = signal<string | null>(null);

  /** Workspace-switcher popover open state. */
  protected readonly wsMenuOpen = signal(false);

  /** First letter of the workspace name — accent-tinted square avatar. */
  protected readonly wsInitial = computed(() => {
    const name = this.org()?.name ?? 'C';
    return name.charAt(0).toUpperCase();
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
