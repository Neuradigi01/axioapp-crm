import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
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
import { NewsDialogComponent } from './news-dialog/news-dialog.component';
import { NewsApiService } from '@app/services/news-api.service';
import {
  BADGE_MAP,
  NEWS_STATUS_OPTIONS,
  NEWS_USER_TYPE_OPTIONS,
  SNACKBAR_ACTION,
  SNACKBAR_DURATION,
} from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_NEWS_DELETED,
  MSG_NEWS_DELETE_FAILED,
  MSG_NEWS_STATUS_UPDATED,
  MSG_NEWS_STATUS_UPDATE_FAILED,
} from '@core/constants/messages.constants';
import { INews, INewsListRequest } from '@app/schemas/news';
import { IConfirmDialogData, IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-admin-news',
  templateUrl: './news.component.html',
  styleUrl: './news.component.scss',
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
export class NewsComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly newsApi = inject(NewsApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    status: ['all'],
    user_type: ['all'],
  });

  readonly data = signal<INews[]>([]);
  readonly dataCount = signal(0);
  readonly isFiltered = signal(false);
  readonly isLoading = signal(false);
  readonly badgeMap = BADGE_MAP;
  readonly statusOptions = NEWS_STATUS_OPTIONS;
  readonly userTypeOptions = NEWS_USER_TYPE_OPTIONS;

  private pageIndex = 0;
  private pageSize = 10;

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    const formVal = this.searchForm.value;
    const payload: INewsListRequest = {
      search: formVal.search || '',
      status: formVal.status || 'all',
      user_type: formVal.user_type || 'all',
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.newsApi.getNewsList(payload);
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
    this.searchForm.reset({ search: '', status: 'all', user_type: 'all' });
    this.pageIndex = 0;
    this.isFiltered.set(false);
    this.loadData();
  }

  onPageChange(event: IPageEvent): void {
    this.pageIndex = event.page_index;
    this.pageSize = event.page_size;
    this.loadData();
  }

  getStatusBadge(isActive: boolean): { color: string; bgVar: string } {
    return isActive ? this.badgeMap['active'] : this.badgeMap['inactive'];
  }

  getUserTypeBadge(userType: string): { color: string; bgVar: string } {
    return this.badgeMap[userType.toLowerCase()] ?? this.badgeMap['general'];
  }

  openAddDialog(): void {
    const dialogRef = this.dialog.open(NewsDialogComponent, {
      data: { mode: 'add' },
      width: '560px',
    });

    dialogRef.afterClosed().subscribe((result: boolean) => {
      if (result) this.loadData();
    });
  }

  openEditDialog(news: INews): void {
    const dialogRef = this.dialog.open(NewsDialogComponent, {
      data: { mode: 'edit', news },
      width: '560px',
    });

    dialogRef.afterClosed().subscribe((result: boolean) => {
      if (result) this.loadData();
    });
  }

  async toggleStatus(news: INews): Promise<void> {
    try {
      const res = await this.newsApi.toggleNewsStatus(news.id);
      if (res.success) {
        this.snackBar.open(MSG_NEWS_STATUS_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.loadData();
      } else {
        this.snackBar.open(res.message || MSG_NEWS_STATUS_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    }
  }

  deleteNews(news: INews): void {
    const dialogData: IConfirmDialogData = {
      title: 'Delete News',
      message: `Are you sure you want to delete "${news.heading}"?`,
      confirmText: 'Delete',
      cancelText: 'Cancel',
      color: 'warn',
    };

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: dialogData,
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(async (confirmed: boolean) => {
      if (!confirmed) return;
      try {
        const res = await this.newsApi.deleteNews(news.id);
        if (res.success) {
          this.snackBar.open(MSG_NEWS_DELETED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
          this.loadData();
        } else {
          this.snackBar.open(res.message || MSG_NEWS_DELETE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        }
      } catch {
        this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    });
  }

  exportToCSV(): void {
    const headers = ['SR#', 'Heading', 'User Type', 'Priority', 'Status', 'Created By', 'Created'];
    const rows = this.data().map((d, i) => [
      (this.pageIndex * this.pageSize + i + 1).toString(),
      `"${d.heading.replace(/"/g, '""')}"`,
      d.user_type,
      d.priority.toString(),
      d.is_active ? 'Active' : 'Inactive',
      d.created_by,
      d.created_at,
    ]);
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'news.csv';
    a.click();
    URL.revokeObjectURL(url);
  }
}
