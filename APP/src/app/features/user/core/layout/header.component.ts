import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  output,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

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
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header.component.html',
})
export class HeaderComponent implements OnInit {
  private readonly auth = inject(FurnitureAuthService);
  private readonly notifications = inject(NotificationsApiService);
  private readonly router = inject(Router);

  readonly toggleSidebar = output<void>();

  protected readonly user = signal<MeResponse | null>(null);
  protected readonly userMenuOpen = signal(false);
  protected readonly tasksOpen = signal(false);
  protected readonly notificationsOpen = signal(false);

  /** Live unread count for the bell badge. */
  protected readonly unreadCount = this.notifications.unreadCount;

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
