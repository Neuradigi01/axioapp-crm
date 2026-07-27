import { ChangeDetectionStrategy, Component, signal, viewChild } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastHostComponent } from '../notifications/toast-host.component';
import { QuickAddFabComponent } from '../shared/quick-add-fab/quick-add-fab.component';
import { CommandPaletteComponent } from '../shared/command-palette/command-palette.component';
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
    CommandPaletteComponent,
    TrialBannerComponent,
    UpgradeModalComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.component.html',
})
export class ShellComponent {
  /** Desktop expand/collapse state (persisted). */
  protected readonly sidebarOpen = signal(this.loadInitialSidebarState());
  /** Mobile off-canvas drawer state (always starts closed, not persisted). */
  protected readonly mobileMenuOpen = signal(false);
  /** Handle on the command palette so the header search-pill click can
   *  toggle it. Cmd+K also toggles it via the component's own document
   *  keydown listener. */
  protected readonly palette = viewChild<CommandPaletteComponent>('palette');

  toggleSidebar(): void {
    const next = !this.sidebarOpen();
    this.sidebarOpen.set(next);
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
  }

  toggleMobileMenu(): void {
    this.mobileMenuOpen.update((v) => !v);
  }

  closeMobileMenu(): void {
    this.mobileMenuOpen.set(false);
  }

  openPalette(): void {
    this.palette()?.toggle();
  }

  private loadInitialSidebarState(): boolean {
    const raw = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) {
      return true;
    }
    return raw === 'true';
  }
}
