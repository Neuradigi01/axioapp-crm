import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { PageLayoutComponent } from '@shared/components/page-layout/page-layout.component';
import { ConfirmationDialogComponent } from '@shared/components/confirmation-dialog/confirmation-dialog.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { BADGE_MAP, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_SUB_ADMIN_STATUS_UPDATED,
  MSG_SUB_ADMIN_STATUS_UPDATE_FAILED,
} from '@core/constants/messages.constants';
import { ISubAdmin, ISubAdminListRequest } from '@app/schemas/admin';
import { IConfirmDialogData, IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-admin-sub-admin-list',
  templateUrl: './sub-admin-list.component.html',
  styleUrl: './sub-admin-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    DatePipe,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
    PageLayoutComponent,
  ],
})
export class SubAdminListComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    status: ['all'],
  });

  readonly data = signal<ISubAdmin[]>([]);
  readonly dataCount = signal(0);
  readonly isFiltered = signal(false);
  readonly isLoading = signal(false);
  readonly badgeMap = BADGE_MAP;

  private pageIndex = 0;
  private pageSize = 10;

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    const formVal = this.searchForm.value;
    const payload: ISubAdminListRequest = {
      search: formVal.search || null,
      status: formVal.status === 'all' ? null : formVal.status === 'active',
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.adminApi.getSubAdminList(payload);
      if (res.success) {
        this.data.set(res.data);
        this.dataCount.set(res.data_count);
      } else {
        this.snackBar.open(res.message || MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  onSubmit(): void {
    this.pageIndex = 0;
    this.isFiltered.set(true);
    this.loadData();
  }

  clearFilters(): void {
    this.searchForm.reset({ search: '', status: 'all' });
    this.pageIndex = 0;
    this.isFiltered.set(false);
    this.loadData();
  }

  onPageChange(event: IPageEvent): void {
    this.pageIndex = event.page_index;
    this.pageSize = event.page_size;
    this.loadData();
  }

  navigateToAdd(): void {
    this.router.navigate([getRoute('add_new_admin').url]);
  }

  navigateToEdit(adminId: string): void {
    this.router.navigate([getRoute('edit_sub_admin').url, adminId]);
  }

  navigateToAccessRights(adminId: string): void {
    this.router.navigate([getRoute('sub_admin_access_rights').url, adminId]);
  }

  toggleStatus(admin: ISubAdmin): void {
    const newStatus = !admin.is_active;
    const action = newStatus ? 'activate' : 'deactivate';
    const dialogData: IConfirmDialogData = {
      title: `${newStatus ? 'Activate' : 'Deactivate'} Sub-Admin`,
      message: `Are you sure you want to ${action} "${admin.name}" (${admin.admin_user_id})?`,
      confirmText: newStatus ? 'Activate' : 'Deactivate',
      color: newStatus ? 'primary' : 'warn',
    };

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: dialogData,
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(async (confirmed: boolean) => {
      if (!confirmed) return;
      try {
        const res = await this.adminApi.toggleSubAdminStatus({
          admin_id: admin.admin_user_id,
          is_active: newStatus,
        });
        if (res.success) {
          this.snackBar.open(MSG_SUB_ADMIN_STATUS_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.loadData();
        } else {
          this.snackBar.open(res.message || MSG_SUB_ADMIN_STATUS_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        }
      } catch {
        this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    });
  }

  getStatusBadge(isActive: boolean): { color: string; bgVar: string; label: string } {
    const key = isActive ? 'active' : 'inactive';
    return { ...this.badgeMap[key], label: isActive ? 'Active' : 'Inactive' };
  }

  exportToCSV(): void {
    const headers = ['SR#', 'Admin ID', 'Name', 'Email', 'Status', 'Route Count', 'Created'];
    const rows = this.data().map((d, i) => [
      (this.pageIndex * this.pageSize + i + 1).toString(),
      d.admin_user_id,
      d.name,
      d.email ?? '',
      d.is_active ? 'Active' : 'Inactive',
      d.route_count.toString(),
      d.created_at,
    ]);
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sub-admins.csv';
    a.click();
    URL.revokeObjectURL(url);
  }
}
