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
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { PageLayoutComponent } from '@shared/components/page-layout/page-layout.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { BADGE_MAP, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_ERROR_LOAD_FAILED } from '@core/constants/messages.constants';
import { IMember, IMemberListRequest } from '@app/schemas/admin';
import { IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-admin-member-search',
  templateUrl: './member-search.component.html',
  styleUrl: './member-search.component.scss',
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
    MatDatepickerModule,
    MatNativeDateModule,
    PageLayoutComponent,
  ],
})
export class MemberSearchComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    status: ['all'],
    date_from: [null as Date | null],
    date_to: [null as Date | null],
  });

  readonly data = signal<IMember[]>([]);
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
    const payload: IMemberListRequest = {
      search: formVal.search || null,
      status: formVal.status === 'all' ? null : formVal.status === 'active',
      date_from: formVal.date_from ? this.formatDate(formVal.date_from) : null,
      date_to: formVal.date_to ? this.formatDate(formVal.date_to) : null,
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.adminApi.getMemberList(payload);
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
    this.searchForm.reset({ search: '', status: 'all', date_from: null, date_to: null });
    this.pageIndex = 0;
    this.isFiltered.set(false);
    this.loadData();
  }

  onPageChange(event: IPageEvent): void {
    this.pageIndex = event.page_index;
    this.pageSize = event.page_size;
    this.loadData();
  }

  navigateToDetail(userId: string): void {
    this.router.navigate([getRoute('member_controls_member_profile').url, userId]);
  }

  getStatusBadge(isActive: boolean): { color: string; bgVar: string; label: string } {
    const key = isActive ? 'active' : 'inactive';
    return { ...this.badgeMap[key], label: isActive ? 'Active' : 'Inactive' };
  }

  exportToCSV(): void {
    const headers = ['SR#', 'User ID', 'Name', 'Email', 'Mobile', 'Status', 'Joined'];
    const rows = this.data().map((d, i) => [
      (this.pageIndex * this.pageSize + i + 1).toString(),
      d.user_id,
      `${d.first_name} ${d.last_name}`,
      d.email,
      d.mobile_no ?? '',
      d.is_active ? 'Active' : 'Inactive',
      d.joining_date ?? '',
    ]);
    const csv = [headers, ...rows].map((r) => r.map((c) => `"${c}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'users.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  private formatDate(date: Date): string {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }
}
