import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import { INotification } from '@app/schemas/notification';

@Injectable({ providedIn: 'root' })
export class NotificationApiService {
  private readonly http = inject(HttpHelperService);

  getNotifications(payload: { page_index: number; page_size: number }): Promise<IPaginatedApiResponse<INotification>> {
    return this.http.Post('/notifications/list', payload) as Promise<IPaginatedApiResponse<INotification>>;
  }

  getUnreadCount(): Promise<IApiResponse<{ count: number }>> {
    return this.http.Get<{ count: number }>('/notifications/unread-count');
  }

  markAsRead(id: number): Promise<IApiResponse<void>> {
    return this.http.Put<void>(`/notifications/${id}/read`, {});
  }

  markAllAsRead(): Promise<IApiResponse<void>> {
    return this.http.Put<void>('/notifications/mark-all-read', {});
  }
}
