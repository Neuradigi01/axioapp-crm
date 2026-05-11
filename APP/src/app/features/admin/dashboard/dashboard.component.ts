import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatCardModule } from '@angular/material/card';
import { AdminApiService } from '@app/services/admin-api.service';
import { DashboardTilesComponent } from '@app/shared/components/dashboard-tiles/dashboard-tiles.component';
import { DashboardNewsComponent } from '@app/shared/components/dashboard-news/dashboard-news.component';
import { IDashboardTile } from '@app/schemas/shared';
import { IRecentRegistration } from '@app/schemas/admin';

@Component({
  selector: 'app-admin-dashboard',
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DashboardTilesComponent, DashboardNewsComponent, MatTableModule, MatCardModule, DatePipe],
})
export class DashboardComponent implements OnInit {
  private readonly adminApi = inject(AdminApiService);

  readonly tiles = signal<IDashboardTile[]>([]);
  readonly recentRegistrations = signal<IRecentRegistration[]>([]);
  readonly displayedColumns = ['user_id', 'name', 'email', 'mobile_no', 'joining_date'];

  async ngOnInit(): Promise<void> {
    try {
      const response = await this.adminApi.getDashboard();
      if (response.success && response.data) {
        const data = response.data;

        this.tiles.set([
          {
            label: 'Total Users',
            value: data.total_users,
            icon: 'groups',
            color: '#3b82f6',
          },
          {
            label: 'Active Users',
            value: data.active_users,
            icon: 'person',
            color: '#22c55e',
          },
          {
            label: 'Today Registrations',
            value: data.today_registrations,
            icon: 'person_add',
            color: '#8b5cf6',
          },
          {
            label: 'Open Tickets',
            value: data.open_tickets,
            icon: 'confirmation_number',
            color: '#f59e0b',
          },
          {
            label: 'Sub-Admin Count',
            value: data.sub_admin_count,
            icon: 'admin_panel_settings',
            color: '#06b6d4',
          },
        ]);

        this.recentRegistrations.set(data.recent_registrations ?? []);
      }
    } catch {
      // API error handled by interceptor
    }
  }
}
