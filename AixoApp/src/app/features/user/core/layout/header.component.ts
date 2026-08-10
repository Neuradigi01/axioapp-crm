import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ThemeChoice, ThemeService } from '@core/services/theme.service';

import { FurnitureAuthService, MeResponse } from '../auth/auth.service';
import { NotificationsApiService } from '../notifications/notifications-api.service';
import { NotificationsPopoverComponent } from '../notifications/notifications-popover.component';
import { MyTasksPopoverComponent } from '../tasks/my-tasks-popover.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    LucideAngularModule,
    MyTasksPopoverComponent,
    NotificationsPopoverComponent,
    RouterLink,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header.component.html',
})
export class HeaderComponent implements OnInit {
  private readonly auth = inject(FurnitureAuthService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly router = inject(Router);
  private readonly themeService = inject(ThemeService);

  /** Emitted when the header's search-pill is clicked. The shell owns
   *  the `CommandPaletteComponent` instance and toggles it in response. */
  readonly openPalette = output<void>();

  protected readonly user = signal<MeResponse | null>(null);
  protected readonly userMenuOpen = signal(false);
  protected readonly tasksOpen = signal(false);
  protected readonly notificationsOpen = signal(false);

  /** Live unread count for the bell badge. */
  protected readonly unreadCount = this.notifications.unreadCount;

  /** Current tenant — drives the mobile workspace label. Desktop shows
   *  the same info in the sidebar's workspace-switcher card. */
  protected readonly org = this.auth.currentOrg;

  /** First letter of the workspace name — accent-tinted mobile avatar. */
  protected readonly wsInitial = computed(() => (this.org()?.name ?? 'C').charAt(0).toUpperCase());

  /** Current theme choice (light/dark/system) — bound to the segmented toggle. */
  protected readonly themeChoice = this.themeService.choice;

  protected pickTheme(c: ThemeChoice): void {
    this.themeService.set(c);
  }

  /** Mobile theme cycle: Light → Dark → System → Light. Mirrors the
   *  three options on the desktop segmented control so mobile users
   *  don't lose access to the "match OS" mode. */
  protected cycleTheme(): void {
    const next: ThemeChoice =
      this.themeChoice() === 'light' ? 'dark' : this.themeChoice() === 'dark' ? 'system' : 'light';
    this.themeService.set(next);
  }

  ngOnInit(): void {
    this.auth.me().subscribe({
      next: (me) => this.user.set(me),
      error: () => this.user.set(null),
    });
    // Open the WS + load initial unread count.
    this.notifications.start();
  }

  toggleUserMenu(): void {
    this.userMenuOpen.update((v) => !v);
    if (this.userMenuOpen()) {
      this.tasksOpen.set(false);
      this.notificationsOpen.set(false);
    }
  }

  toggleTasks(): void {
    this.tasksOpen.update((v) => !v);
    if (this.tasksOpen()) {
      this.userMenuOpen.set(false);
      this.notificationsOpen.set(false);
    }
  }

  toggleNotifications(): void {
    this.notificationsOpen.update((v) => !v);
    if (this.notificationsOpen()) {
      this.userMenuOpen.set(false);
      this.tasksOpen.set(false);
    }
  }

  closeNotifications(): void {
    this.notificationsOpen.set(false);
  }

  logout(): void {
    this.auth.logout().subscribe({
      next: () => this.afterLogout(),
      error: () => this.afterLogout(),
    });
  }

  private afterLogout(): void {
    this.notifications.stop();
    this.auth.clearSession();
    this.userMenuOpen.set(false);
    this.tasksOpen.set(false);
    this.notificationsOpen.set(false);
    this.router.navigate(['/accounts/login']);
  }
}
