import { Component, ChangeDetectionStrategy, input, signal, inject, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ILoginHistoryRecord, IBadgeConfig } from '@app/schemas/common';
import { LoginHistoryApiService } from '@app/services/login-history-api.service';
import { AuthService } from '@core/services/auth.service';
import { SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';

const STATUS_BADGE_MAP: Record<string, IBadgeConfig> = {
  Active: { color: 'var(--badge-active-color)', bgVar: 'var(--badge-active-bg)' },
  'Current Session': { color: 'var(--badge-active-color)', bgVar: 'var(--badge-active-bg)' },
  '2FA-Pending': { color: 'var(--badge-in-progress-color)', bgVar: 'var(--badge-in-progress-bg)' },
  Failed: { color: 'var(--badge-inactive-color)', bgVar: 'var(--badge-inactive-bg)' },
};

const DEFAULT_BADGE: IBadgeConfig = {
  color: 'var(--badge-closed-color)',
  bgVar: 'var(--badge-closed-bg)',
};

@Component({
  selector: 'app-login-history-table',
  templateUrl: './login-history-table.component.html',
  styleUrl: './login-history-table.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    MatButtonModule,
    MatIconModule,
    MatPaginatorModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
  ],
})
export class LoginHistoryTableComponent implements OnInit {
  readonly showUserColumns = input(false);
  readonly pageTitle = input('Login History');
  readonly pageSubtitle = input('');

  private readonly api = inject(LoginHistoryApiService);
  private readonly auth = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);

  readonly data = signal<ILoginHistoryRecord[]>([]);
  readonly totalRecords = signal(0);
  readonly isLoading = signal(false);
  readonly pageSize = signal(10);
  readonly pageIndex = signal(0);

  private currentTokenId = 0;

  ngOnInit(): void {
    const details = this.auth.getUserDetails();
    this.currentTokenId = details?.tokenId ?? 0;
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    try {
      const payload: Record<string, unknown> = {
        page_index: this.pageIndex(),
        page_size: this.pageSize(),
      };

      if (this.showUserColumns()) {
        payload['match_exact_user_id'] = false;
      }

      const res = await this.api.getLoginHistory(payload);
      if (res.success) {
        this.data.set(res.data ?? []);
        this.totalRecords.set(res.data_count ?? 0);
      }
    } catch {
      // silently fail
    } finally {
      this.isLoading.set(false);
    }
  }

  onPageChange(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadData();
  }

  async logoutSession(tokenId: number): Promise<void> {
    try {
      const res = await this.api.logoutSession(tokenId);
      this.snackBar.open(res.message, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      if (res.success) {
        this.loadData();
      }
    } catch {
      this.snackBar.open('Failed to logout session', SNACKBAR_ACTION, {
        duration: SNACKBAR_DURATION,
      });
    }
  }

  openMap(lat: string, lng: string): void {
    window.open(`https://www.google.com/maps?q=${lat},${lng}`, '_blank');
  }

  getDeviceIcon(deviceType: string): string {
    switch (deviceType?.toLowerCase()) {
      case 'desktop':
        return 'computer';
      case 'mobile':
        return 'smartphone';
      case 'tablet':
        return 'tablet_mac';
      default:
        return 'devices';
    }
  }

  getStatusBadge(status: string): IBadgeConfig {
    return STATUS_BADGE_MAP[status] ?? DEFAULT_BADGE;
  }

  isCurrentSession(record: ILoginHistoryRecord): boolean {
    return record.token_id === this.currentTokenId;
  }

  canLogout(record: ILoginHistoryRecord): boolean {
    return record.login_status === 'Active' && !this.isCurrentSession(record);
  }
}
