import { Component, ChangeDetectionStrategy, inject, signal, computed, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { PageLayoutComponent } from '@shared/components/page-layout/page-layout.component';
import { TicketApiService, ITicketListRequest } from '@app/services/ticket-api.service';
import { SharedService } from '@core/services/shared.service';
import { getRoute } from '@core/services/routes-helper.service';
import { BADGE_MAP, ROLE_ADMIN, SNACKBAR_ACTION, SNACKBAR_DURATION, TICKET_STATUS_OPTIONS, TICKET_PRIORITY_OPTIONS } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_ERROR_LOAD_FAILED } from '@core/constants/messages.constants';
import { ITicket } from '@app/schemas/ticket';
import { IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-support-ticket-list',
  templateUrl: './ticket-list.component.html',
  styleUrl: './ticket-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    DatePipe,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    PageLayoutComponent,
  ],
})
export class TicketListComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly ticketApi = inject(TicketApiService);
  private readonly shared = inject(SharedService);
  private readonly snackBar = inject(MatSnackBar);

  readonly isAdmin = computed(() => this.shared.userDetails?.role === ROLE_ADMIN);

  readonly searchForm: FormGroup = this.fb.group({
    search: [''],
    status: ['all'],
    priority: ['all'],
    from_user_id: [''],
  });

  readonly data = signal<ITicket[]>([]);
  readonly dataCount = signal(0);
  readonly isFiltered = signal(false);
  readonly isLoading = signal(false);
  readonly badgeMap = BADGE_MAP;
  readonly statusOptions = TICKET_STATUS_OPTIONS;
  readonly priorityOptions = TICKET_PRIORITY_OPTIONS;

  private pageIndex = 0;
  private pageSize = 10;

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    const formVal = this.searchForm.value;
    const payload: ITicketListRequest = {
      search_term: formVal.search || null,
      status: formVal.status === 'all' ? null : formVal.status,
      priority: this.isAdmin() && formVal.priority !== 'all' ? formVal.priority : null,
      from_user_id: this.isAdmin() && formVal.from_user_id?.trim() ? formVal.from_user_id.trim() : null,
      page_index: this.pageIndex,
      page_size: this.pageSize,
    };

    try {
      const res = await this.ticketApi.getTickets(payload);
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
    this.searchForm.reset({ search: '', status: 'all', priority: 'all', from_user_id: '' });
    this.pageIndex = 0;
    this.isFiltered.set(false);
    this.loadData();
  }

  onPageChange(event: IPageEvent): void {
    this.pageIndex = event.page_index;
    this.pageSize = event.page_size;
    this.loadData();
  }

  viewTicket(ticketId: number): void {
    const routeKey = this.isAdmin() ? 'admin_support_view_ticket' : 'user_support_view_ticket';
    this.router.navigate([getRoute(routeKey).url, ticketId]);
  }

  getStatusBadge(status: string): { color: string; bgVar: string; label: string } {
    const key = status.toLowerCase();
    const badge = this.badgeMap[key];
    return badge ? { ...badge, label: status } : { color: 'var(--page-text)', bgVar: 'var(--surface-2)', label: status };
  }

  exportToCSV(): void {
    const isAdminView = this.isAdmin();
    const headers = ['SR#', 'Ticket No', 'Subject', 'Status', 'Priority', 'Date', 'Attachments'];
    if (isAdminView) headers.splice(3, 0, 'From User');

    const rows = this.data().map((d, i) => {
      const row = [
        (this.pageIndex * this.pageSize + i + 1).toString(),
        d.ticket_no,
        d.subject,
        d.status,
        d.priority,
        d.created_at,
        d.attachment_count.toString(),
      ];
      if (isAdminView) row.splice(3, 0, d.from_user_id);
      return row;
    });

    const csv = [headers, ...rows].map((r) => r.map((c) => `"${c}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'tickets.csv';
    a.click();
    URL.revokeObjectURL(url);
  }
}
