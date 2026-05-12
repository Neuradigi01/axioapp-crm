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
import { MyTasksPopoverComponent } from '../tasks/my-tasks-popover.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [LucideAngularModule, MyTasksPopoverComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header.component.html',
})
export class HeaderComponent implements OnInit {
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);

  readonly toggleSidebar = output<void>();

  protected readonly user = signal<MeResponse | null>(null);
  protected readonly userMenuOpen = signal(false);
  protected readonly tasksOpen = signal(false);

  ngOnInit(): void {
    this.auth.me().subscribe({
      next: (me) => this.user.set(me),
      error: () => this.user.set(null),
    });
  }

  toggleUserMenu(): void {
    this.userMenuOpen.update((v) => !v);
    if (this.userMenuOpen()) this.tasksOpen.set(false);
  }

  toggleTasks(): void {
    this.tasksOpen.update((v) => !v);
    if (this.tasksOpen()) this.userMenuOpen.set(false);
  }

  logout(): void {
    this.auth.logout().subscribe({
      next: () => this.afterLogout(),
      error: () => this.afterLogout(),
    });
  }

  private afterLogout(): void {
    this.auth.clearSession();
    this.userMenuOpen.set(false);
    this.tasksOpen.set(false);
    this.router.navigate(['/accounts/login']);
  }
}
