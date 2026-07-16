import {
  Component,
  ChangeDetectionStrategy,
  inject,
  signal,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatDividerModule } from '@angular/material/divider';
import { ThemeService } from '@core/services/theme.service';
import { AuthService } from '@core/services/auth.service';
import { RoutesHelperService, getRoute } from '@core/services/routes-helper.service';
import { MatDialog } from '@angular/material/dialog';
import { AdminApiService } from '@app/services/admin-api.service';
import { PopupApiService } from '@app/services/popup-api.service';
import { PopupDisplayComponent } from '@shared/components/popup-display/popup-display.component';
import { AppSettings } from '@app/app.settings';
import { INavMenuItem } from '@app/schemas/route';
import { ROLE_ADMIN, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { FooterComponent } from '@shared/components/footer/footer.component';
import { NotificationBellComponent } from '@shared/components/notification-bell/notification-bell.component';
import { PushNotificationService } from '@core/services/push-notification.service';
import { AppConfigApiService } from '@app/services/app-config-api.service';
import { MatSnackBar } from '@angular/material/snack-bar';

@Component({
  selector: 'app-admin-layout',
  templateUrl: './admin-layout.component.html',
  styleUrl: './admin-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatSidenavModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    MatDividerModule,
    FooterComponent,
    NotificationBellComponent,
  ],
})
export class AdminLayoutComponent implements OnInit, OnDestroy {
  private readonly breakpointObserver = inject(BreakpointObserver);
  readonly theme = inject(ThemeService);
  private readonly auth = inject(AuthService);
  private readonly routesHelper = inject(RoutesHelperService);
  private readonly adminApi = inject(AdminApiService);
  private readonly popupApi = inject(PopupApiService);
  private readonly dialog = inject(MatDialog);
  private readonly pushNotification = inject(PushNotificationService);
  private readonly appConfigService = inject(AppConfigApiService);
  private readonly snackBar = inject(MatSnackBar);
  private unsubscribeForeground: (() => void) | null = null;

  readonly isMobile = signal(false);
  readonly sidenavOpened = signal(true);
  readonly menuItems = signal<INavMenuItem[]>([]);
  readonly expandedMenuIds = signal<Set<number>>(new Set());
  readonly adminName = signal('');
  readonly adminInitial = signal('A');
  readonly isSuperAdmin = signal(true);
  readonly profileImageUrl = signal<string | null>(null);

  readonly profileUrl = getRoute('admin_profile').url;
  readonly changePasswordUrl = getRoute('admin_change_password').url;
  readonly securityUrl = getRoute('admin_security').url;

  get roleLabel(): string {
    return this.isSuperAdmin() ? 'Super Admin' : 'Sub-Admin';
  }

  ngOnInit(): void {
    this.breakpointObserver
      .observe([Breakpoints.Handset, Breakpoints.TabletPortrait])
      .subscribe((result) => {
        this.isMobile.set(result.matches);
        this.sidenavOpened.set(!result.matches);
      });

    const userDetails = this.auth.getUserDetails();
    if (userDetails) {
      this.adminName.set(userDetails.userId);
      this.adminInitial.set(userDetails.userId.charAt(0).toUpperCase() || 'A');
      this.isSuperAdmin.set(userDetails.isSuperAdmin);
      const menus = this.routesHelper.getSideNavMenusFromAccessRights(
        ROLE_ADMIN,
        userDetails.accessRights
      );
      this.menuItems.set(menus);
    }

    this.loadProfileImage();
    this.showPopupIfNeeded();
    this.initPushNotifications();
  }

  ngOnDestroy(): void {
    if (this.unsubscribeForeground) {
      this.unsubscribeForeground();
      this.unsubscribeForeground = null;
    }
  }

  private async initPushNotifications(): Promise<void> {
    try {
      const cfg = this.appConfigService.config();
      if (cfg?.push_notification_enabled && cfg.firebase_config) {
        await this.pushNotification.initialize(cfg.firebase_config);
        await this.pushNotification.requestPermissionAndRegisterToken(cfg.firebase_config.vapid_key);
        this.unsubscribeForeground = this.pushNotification.onForegroundMessage((payload) => {
          const title = payload.notification?.title || 'New notification';
          this.snackBar.open(title, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        });
      }
    } catch {
      // Silently fail — push is best-effort
    }
  }

  private async loadProfileImage(): Promise<void> {
    try {
      const response = await this.adminApi.getProfile();
      if (response.success && response.data?.profile_image) {
        this.profileImageUrl.set(`${AppSettings.StaticBaseUrl}/${response.data.profile_image}`);
      }
    } catch {
      // Silently fail — avatar falls back to initial
    }
  }

  private async showPopupIfNeeded(): Promise<void> {
    if (sessionStorage.getItem('popup_shown')) return;

    try {
      const res = await this.popupApi.getActivePopup();
      if (res.success && res.data) {
        sessionStorage.setItem('popup_shown', 'true');
        this.dialog.open(PopupDisplayComponent, {
          data: { image_path: res.data.image_path, title: res.data.title },
          maxWidth: '90vw',
          hasBackdrop: true,
        });
      }
    } catch {
      // Silently fail
    }
  }

  toggleSidenav(): void {
    this.sidenavOpened.update((v) => !v);
  }

  toggleExpanded(menuId: number): void {
    this.expandedMenuIds.update((ids) => {
      const next = new Set(ids);
      if (next.has(menuId)) {
        next.delete(menuId);
      } else {
        next.add(menuId);
      }
      return next;
    });
  }

  isExpanded(menuId: number): boolean {
    return this.expandedMenuIds().has(menuId);
  }

  onMenuClick(): void {
    if (this.isMobile()) {
      this.sidenavOpened.set(false);
    }
  }

  logout(): void {
    this.auth.logout();
  }

  getMenuUrl(item: INavMenuItem): string {
    return item.route.url;
  }
}
