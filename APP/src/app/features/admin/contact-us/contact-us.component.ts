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
import { ContactDetailDialogComponent } from './contact-detail-dialog/contact-detail-dialog.component';
import { ContactUsApiService } from '@app/services/contact-us-api.service';
import { BADGE_MAP, CONTACT_TYPE_OPTIONS, SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_ERROR_LOAD_FAILED } from '@core/constants/messages.constants';
import { IContactUs, IContactUsListRequest } from '@app/schemas/contact-us';
import { IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-admin-contact-us',
  templateUrl: './contact-us.component.html',
  styleUrl: './contact-us.component.scss',
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
export class ContactUsComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly contactUsApi = inject(ContactUsApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    type: ['all'],
  });

  readonly data = signal<IContactUs[]>([]);
  readonly dataCount = signal(0);
  readonly isFiltered = signal(false);
  readonly isLoading = signal(false);
  readonly badgeMap = BADGE_MAP;
  readonly typeOptions = CONTACT_TYPE_OPTIONS;

  private pageIndex = 0;
  private pageSize = 10;

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    const formVal = this.searchForm.value;
    const payload: IContactUsListRequest = {
      search: formVal.search || '',
      type: formVal.type || 'all',
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.contactUsApi.getContactUsList(payload);
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
    this.searchForm.reset({ search: '', type: 'all' });
    this.pageIndex = 0;
    this.isFiltered.set(false);
    this.loadData();
  }

  onPageChange(event: IPageEvent): void {
    this.pageIndex = event.page_index;
    this.pageSize = event.page_size;
    this.loadData();
  }

  getTypeBadge(type: string): { color: string; bgVar: string } {
    return this.badgeMap[type.toLowerCase()] ?? this.badgeMap['general'];
  }

  viewDetail(contact: IContactUs): void {
    this.dialog.open(ContactDetailDialogComponent, {
      data: contact,
      width: '560px',
    });
  }
}
