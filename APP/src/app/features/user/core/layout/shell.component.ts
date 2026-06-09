import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastHostComponent } from '../notifications/toast-host.component';
import { QuickAddFabComponent } from '../shared/quick-add-fab/quick-add-fab.component';
import { TrialBannerComponent } from '../billing/components/trial-banner/trial-banner.component';
import { UpgradeModalComponent } from '../billing/components/upgrade-modal/upgrade-modal.component';
import { SidebarComponent } from './sidebar.component';
import { HeaderComponent } from './header.component';

const SIDEBAR_STORAGE_KEY = 'furniturecrm:sidebar-open';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    RouterOutlet,
    SidebarComponent,
    HeaderComponent,
    ToastHostComponent,
    QuickAddFabComponent,
    TrialBannerComponent,
    UpgradeModalComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.component.html',
})
export class ShellComponent {
  protected readonly sidebarOpen = signal(this.loadInitialSidebarState());

  toggleSidebar(): void {
    const next = !this.sidebarOpen();
    this.sidebarOpen.set(next);
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
  }

  private loadInitialSidebarState(): boolean {
    const raw = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) {
      return true;
    }
    return raw === 'true';
  }
}
