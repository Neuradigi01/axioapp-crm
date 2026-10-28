import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { PageLayoutComponent } from '@shared/components/page-layout/page-layout.component';
import { NewsletterApiService } from '@app/services/newsletter-api.service';
import { BADGE_MAP, NEWSLETTER_STATUS_OPTIONS, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_ERROR_LOAD_FAILED } from '@core/constants/messages.constants';
import { INewsletterSubscriber, INewsletterListRequest } from '@app/schemas/newsletter';
import { IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-admin-newsletter',
  templateUrl: './newsletter.component.html',
  styleUrl: './newsletter.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    DatePipe,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    PageLayoutComponent,
  ],
})
export class NewsletterComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly newsletterApi = inject(NewsletterApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    status: ['all'],
  });

  readonly data = signal<INewsletterSubscriber[]>([]);
  readonly dataCount = signal(0);
  readonly isFiltered = signal(false);
  readonly isLoading = signal(false);
  readonly badgeMap = BADGE_MAP;
  readonly statusOptions = NEWSLETTER_STATUS_OPTIONS;

  private pageIndex = 0;
  private pageSize = 10;

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    const formVal = this.searchForm.value;
    const payload: INewsletterListRequest = {
      search: formVal.search || '',
      status: formVal.status || 'all',
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.newsletterApi.getSubscriberList(payload);
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

  getStatusBadge(isSubscribed: boolean): { color: string; bgVar: string } {
    return isSubscribed ? this.badgeMap['subscribed'] : this.badgeMap['unsubscribed'];
  }
}
