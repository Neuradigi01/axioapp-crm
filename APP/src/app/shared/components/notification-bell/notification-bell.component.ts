import {
  Component,
  ChangeDetectionStrategy,
  inject,
  signal,
  effect,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatBadgeModule } from '@angular/material/badge';
import { MatDividerModule } from '@angular/material/divider';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NotificationApiService } from '@app/services/notification-api.service';
import { INotification } from '@app/schemas/notification';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { MSG_NOTIFICATIONS_MARKED_READ } from '@core/constants/messages.constants';
import { PushNotificationService } from '@core/services/push-notification.service';
import { DatePipe } from '@angular/common';

const POLL_INTERVAL_MS = 60_000;
const DROPDOWN_PAGE_SIZE = 7;

@Component({
  selector: 'app-notification-bell',
  templateUrl: './notification-bell.component.html',
  styleUrl: './notification-bell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatBadgeModule,
    MatDividerModule,
    DatePipe,
  ],
})
export class NotificationBellComponent implements OnInit, OnDestroy {
  private readonly notificationApi = inject(NotificationApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly pushNotification = inject(PushNotificationService);
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    effect(() => {
      this.pushNotification.pushReceived();
      this.fetchUnreadCount();
    });
  }

  readonly unreadCount = signal(0);
  readonly notifications = signal<INotification[]>([]);
  readonly isLoading = signal(false);

  ngOnInit(): void {
    this.fetchUnreadCount();
    this.pollTimer = setInterval(() => this.fetchUnreadCount(), POLL_INTERVAL_MS);
  }

  ngOnDestroy(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async onMenuOpened(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.notificationApi.getNotifications({
        page_index: 0,
        page_size: DROPDOWN_PAGE_SIZE,
      });
      if (res.success) {
        this.notifications.set(res.data);
      }
    } catch {
      // Silently fail
    } finally {
      this.isLoading.set(false);
    }
  }

  async markAsRead(notification: INotification, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    if (notification.is_read) return;

    try {
      const res = await this.notificationApi.markAsRead(notification.id);
      if (res.success) {
        this.notifications.update((list) =>
          list.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n))
        );
        this.unreadCount.update((c) => Math.max(0, c - 1));
      }
    } catch {
      // Silently fail
    }
  }

  async markAllAsRead(): Promise<void> {
    try {
      const res = await this.notificationApi.markAllAsRead();
      if (res.success) {
        this.notifications.update((list) => list.map((n) => ({ ...n, is_read: true })));
        this.unreadCount.set(0);
        this.snackBar.open(MSG_NOTIFICATIONS_MARKED_READ, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
      }
    } catch {
      // Silently fail
    }
  }

  private async fetchUnreadCount(): Promise<void> {
    try {
      const res = await this.notificationApi.getUnreadCount();
      if (res.success) {
        this.unreadCount.set(res.data.count);
      }
    } catch {
      // Silently fail
    }
  }
}
